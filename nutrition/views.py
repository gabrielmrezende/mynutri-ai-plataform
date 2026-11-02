import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from .models import Anamnese, DietJob, DietPlan, Meal, MealRegenerationLog
from .serializers import (
    AnamneseSerializer,
    DietPlanSerializer,
    DietPlanSummarySerializer,
    validate_free_text,
)
from .services import DietGenerationError, TransientAIError
from .tasks import generate_diet_task
from .pdf_generator import generate_diet_pdf

logger = logging.getLogger(__name__)

# Jobs em 'pending' por mais deste tempo nunca foram pegos por um worker (fila parada).
PENDING_JOB_TIMEOUT = timedelta(minutes=10)
# Jobs em 'processing' por mais deste tempo são considerados travados (worker morreu).
# Precisa ser maior que o time_limit da task (9 min) para não expirar job ainda vivo.
PROCESSING_JOB_TIMEOUT = timedelta(minutes=15)

MSG_JOB_PENDING_EXPIRED = (
    'A geração não começou a tempo: o serviço está sobrecarregado. '
    'Tente gerar sua dieta novamente.'
)
MSG_JOB_PROCESSING_EXPIRED = (
    'Geração interrompida: o servidor foi reiniciado durante o processamento. '
    'Tente gerar sua dieta novamente.'
)
MSG_JOB_ENQUEUE_FAILED = (
    'Não foi possível iniciar a geração da sua dieta agora. Tente novamente em instantes.'
)
MSG_JOB_FAILED_DEFAULT = 'Falha ao gerar dieta. Tente novamente.'

# Regenerações pontuais de refeição por DietPlan por dia (dia local, TIME_ZONE)
MEAL_REGEN_DAILY_LIMIT = 3


def expire_stale_jobs(user) -> int:
    """
    Marca como 'failed' os jobs do usuário que ficaram presos:
      - pending há mais de PENDING_JOB_TIMEOUT (nenhum worker pegou a mensagem)
      - processing há mais de PROCESSING_JOB_TIMEOUT (worker morreu no meio)

    Updates condicionais (WHERE status=...) — seguros contra corrida com o worker:
    se o worker concluir antes, o filtro não casa; se concluir depois, a task
    percebe que o job saiu de 'processing' e descarta o plano.
    """
    now = timezone.now()
    expired = DietJob.objects.filter(
        user=user,
        status=DietJob.STATUS_PENDING,
        updated_at__lt=now - PENDING_JOB_TIMEOUT,
    ).update(status=DietJob.STATUS_FAILED, error_message=MSG_JOB_PENDING_EXPIRED, updated_at=now)
    expired += DietJob.objects.filter(
        user=user,
        status=DietJob.STATUS_PROCESSING,
        updated_at__lt=now - PROCESSING_JOB_TIMEOUT,
    ).update(status=DietJob.STATUS_FAILED, error_message=MSG_JOB_PROCESSING_EXPIRED, updated_at=now)
    if expired:
        logger.warning('%d DietJob(s) do usuário %s expirados (travados).', expired, user.pk)
    return expired


def _local_day_start():
    """Início do dia corrente no fuso do projeto (TIME_ZONE), como datetime aware."""
    today = timezone.localdate()
    return timezone.make_aware(datetime.combine(today, time.min))


def _regenerations_used_today(diet_plan_id: int) -> int:
    """
    Regenerações consumidas hoje para o plano. Conta TODOS os logs do dia —
    inclusive desfeitos e reservas em andamento — para que regenerar+desfazer
    não permita regenerações ilimitadas.
    """
    return MealRegenerationLog.objects.filter(
        diet_plan_id=diet_plan_id,
        created_at__gte=_local_day_start(),
    ).count()


def regenerations_remaining_today(diet_plan_id: int) -> int:
    return max(0, MEAL_REGEN_DAILY_LIMIT - _regenerations_used_today(diet_plan_id))


def _recalculate_plan_totals(raw: dict) -> int:
    """
    Recalcula calories/macros do raw_response a partir dos foods de cada refeição.
    Altera `raw` in-place e retorna o total de calorias.
    """
    total_cal = 0
    total_prot = 0.0
    total_carb = 0.0
    total_fat = 0.0
    for m in raw.get('meals', []):
        for f in m.get('foods', []):
            total_cal  += f.get('calories',  0) or 0
            total_prot += f.get('protein_g', 0) or 0
            total_carb += f.get('carbs_g',   0) or 0
            total_fat  += f.get('fat_g',     0) or 0

    raw['calories'] = total_cal
    raw['macros'] = {
        'protein_g': round(total_prot),
        'carbs_g':   round(total_carb),
        'fat_g':     round(total_fat),
    }
    return total_cal


def _serialize_diet_plan(diet_plan: DietPlan) -> dict:
    """DietPlanSerializer + cota de regenerações restantes hoje (C6)."""
    data = dict(DietPlanSerializer(diet_plan).data)
    data['regenerations_remaining_today'] = regenerations_remaining_today(diet_plan.pk)
    return data


class AnamneseAPIView(APIView):
    """
    POST /api/anamnese
    Salva as respostas do questionário nutricional do usuário logado.
    Requer: Authorization: Bearer <token>
    Limite: throttle scope 'anamnese' (protege contra flood de registros).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'anamnese'

    def post(self, request):
        serializer = AnamneseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        anamnese = serializer.save(user=request.user)
        return Response(
            AnamneseSerializer(anamnese).data,
            status=status.HTTP_201_CREATED,
        )


class AnamneseLastAPIView(APIView):
    """
    GET /api/v1/anamnese/last
    Retorna a anamnese mais recente do usuário logado para pré-preenchimento do questionário.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        anamnese = (
            Anamnese.objects.filter(user=request.user)
            .order_by('-answered_at')
            .first()
        )
        if not anamnese:
            return Response(
                {'detail': 'Nenhuma anamnese encontrada.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(AnamneseSerializer(anamnese).data, status=status.HTTP_200_OK)


def _enqueue_diet_job(job_id: int) -> None:
    """
    Enfileira a task após o commit da transação (evita o worker ler um job
    que ainda não existe no banco). Se o broker estiver fora do ar, o job é
    marcado como failed em vez de ficar 'pending' para sempre.
    """
    try:
        generate_diet_task.delay(job_id)
    except Exception:
        logger.exception('Falha ao enfileirar DietJob#%s — marcando como failed.', job_id)
        DietJob.objects.filter(pk=job_id, status=DietJob.STATUS_PENDING).update(
            status=DietJob.STATUS_FAILED,
            error_message=MSG_JOB_ENQUEUE_FAILED,
            updated_at=timezone.now(),
        )


class DietGenerateAPIView(APIView):
    """
    POST /api/v1/diet/generate
    Enfileira a geração de dieta via Celery e retorna imediatamente com o job_id.

    Fluxo assíncrono:
        1. Expira jobs travados do usuário (pending > 10 min, processing > 15 min)
        2. Se já houver job em andamento, devolve o mesmo job_id (idempotente)
        3. Verifica a cota diária (gerações não falhas nas últimas 24h)
        4. Cria DietJob(status='pending') e enfileira a task no on_commit
        5. Retorna 202 Accepted + {"job_id": <id>}
        6. Frontend faz polling em GET /api/v1/diet/status/<job_id>

    Modo síncrono (dev sem Redis / CELERY_TASK_ALWAYS_EAGER=True):
        O Celery executa a task inline antes de retornar — o job já estará
        'done' ou 'failed' na primeira chamada de polling.

    Limites:
        - Cota de negócio: DIET_GENERATE_DAILY_LIMIT gerações por 24h. Jobs que
          falharam/expiraram NÃO contam (o usuário pode tentar de novo).
        - Throttle DRF 'diet_generate': anti-abuso mais folgado, conta todas as
          requisições (inclusive as que falham) — protege a API de IA de flood.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'diet_generate'

    def post(self, request):
        anamnese = (
            Anamnese.objects.filter(user=request.user)
            .order_by('-answered_at')
            .first()
        )

        if not anamnese:
            return Response(
                {'error': 'Nenhuma anamnese encontrada. Responda o questionário primeiro.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Desbloqueia o usuário se o job anterior travou (worker morreu, fila parada)
        expire_stale_jobs(request.user)

        in_progress = DietJob.objects.filter(
            user=request.user,
            status__in=[DietJob.STATUS_PENDING, DietJob.STATUS_PROCESSING],
        ).first()
        if in_progress:
            return Response(
                {'job_id': in_progress.pk, 'status': in_progress.status},
                status=status.HTTP_202_ACCEPTED,
            )

        daily_limit = getattr(settings, 'DIET_GENERATE_DAILY_LIMIT', 3)
        used = DietJob.objects.filter(
            user=request.user,
            created_at__gte=timezone.now() - timedelta(days=1),
        ).exclude(status=DietJob.STATUS_FAILED).count()
        if used >= daily_limit:
            return Response(
                {
                    'error': (
                        f'Limite de {daily_limit} dietas geradas por dia atingido. '
                        'Tente novamente amanhã.'
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        job = DietJob.objects.create(user=request.user, anamnese=anamnese)

        # delay() enfileira no Redis (prod) ou executa inline (dev com always_eager).
        # on_commit: com ATOMIC_REQUESTS/transação externa, só enfileira após o commit.
        transaction.on_commit(lambda: _enqueue_diet_job(job.pk))

        logger.info('DietJob#%s criado para usuário %s.', job.pk, request.user.id)

        return Response({'job_id': job.pk, 'status': job.status}, status=status.HTTP_202_ACCEPTED)


class DietJobStatusAPIView(APIView):
    """
    GET /api/v1/diet/status/<job_id>
    Retorna o estado atual de um job de geração de dieta.

    Resposta:
        pending/processing: {"status": "...", "diet_plan_id": null}
        done:               {"status": "done", "diet_plan_id": <id>}
        failed:             {"status": "failed", "error": "<mensagem amigável>"}

    Throttle próprio ('job_status') — o frontend faz polling a cada 3s, o que
    estouraria o limite global por usuário.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'job_status'

    def get(self, request, job_id):
        if not DietJob.objects.filter(pk=job_id, user=request.user).exists():
            return Response({'error': 'Job não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Auto-recuperação: job travado vira 'failed' para o frontend exibir erro.
        expire_stale_jobs(request.user)
        job = DietJob.objects.get(pk=job_id, user=request.user)

        payload = {'status': job.status, 'diet_plan_id': None}

        if job.status == DietJob.STATUS_DONE and job.diet_plan_id:
            payload['diet_plan_id'] = job.diet_plan_id

        if job.status == DietJob.STATUS_FAILED:
            # error_message é sempre gravado com mensagens amigáveis (tasks.user_message_for)
            payload['error'] = job.error_message or MSG_JOB_FAILED_DEFAULT

        return Response(payload, status=status.HTTP_200_OK)


class DietAPIView(APIView):
    """
    GET /api/diet
    Retorna o plano alimentar mais recente do usuário logado
    (+ regenerations_remaining_today).
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        diet_plan = (
            DietPlan.objects.filter(user=request.user)
            .prefetch_related('meals')
            .order_by('-created_at')
            .first()
        )

        if not diet_plan:
            return Response(
                {'error': 'Você ainda não possui um plano alimentar gerado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(_serialize_diet_plan(diet_plan), status=status.HTTP_200_OK)


class DietListAPIView(APIView):
    """
    GET /api/v1/diet/list
    Retorna o histórico de planos alimentares do usuário logado (paginado, 10/página).
    Parâmetros: ?page=<n>
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]
    PAGE_SIZE = 10

    def get(self, request):
        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (ValueError, TypeError):
            page = 1

        offset = (page - 1) * self.PAGE_SIZE
        qs = DietPlan.objects.filter(user=request.user).order_by('-created_at')
        total = qs.count()
        # Não carrega o raw_response inteiro (dezenas de KB por plano): extrai só
        # a chave 'macros' no banco, que é o único dado do JSON usado na listagem.
        diet_plans = list(
            qs.defer('raw_response')
            .annotate(_macros=F('raw_response__macros'))[offset:offset + self.PAGE_SIZE]
        )
        for plan in diet_plans:
            plan.raw_response = {'macros': plan._macros} if plan._macros is not None else {}

        serializer = DietPlanSummarySerializer(diet_plans, many=True)
        return Response({
            'results': serializer.data,
            'count': total,
            'page': page,
            'total_pages': max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE),
        }, status=status.HTTP_200_OK)


class DietDetailAPIView(APIView):
    """
    GET /api/v1/diet/<id>
    Retorna um plano alimentar específico do usuário logado pelo ID
    (+ regenerations_remaining_today).
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            diet_plan = (
                DietPlan.objects.prefetch_related('meals')
                .get(pk=pk, user=request.user)
            )
        except DietPlan.DoesNotExist:
            return Response(
                {'error': 'Plano alimentar não encontrado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(_serialize_diet_plan(diet_plan), status=status.HTTP_200_OK)


class DietSubstitutionsAPIView(APIView):
    """
    PATCH /api/v1/diet/<id>/substitutions
    Substitui a lista de substituições de um DietPlan do usuário autenticado.
    Body: { "substitutions": [{ "food": "...", "alternatives": ["...", ...] }] }
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not DietPlan.objects.filter(pk=pk, user=request.user).exists():
            return Response(
                {'error': 'Plano alimentar não encontrado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        substitutions = request.data.get('substitutions')
        if not isinstance(substitutions, list):
            return Response(
                {'error': 'O campo "substitutions" deve ser uma lista.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(substitutions) > 50:
            return Response(
                {'error': 'Máximo de 50 substituições permitido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        errors = []
        for i, item in enumerate(substitutions):
            if not isinstance(item, dict):
                errors.append(f'Item {i}: formato inválido.')
                continue
            food = item.get('food')
            alts = item.get('alternatives')
            if not isinstance(food, str) or not food.strip():
                errors.append(f'Item {i}: "food" não pode ser vazio.')
            elif len(food) > 100:
                errors.append(f'Item {i}: "food" excede 100 caracteres.')
            if not isinstance(alts, list) or not alts:
                errors.append(f'Item {i}: "alternatives" deve ser uma lista não vazia.')
            else:
                for j, alt in enumerate(alts):
                    if not isinstance(alt, str) or not alt.strip():
                        errors.append(f'Item {i}, alternativa {j}: não pode ser vazia.')
                    elif len(alt) > 100:
                        errors.append(f'Item {i}, alternativa {j}: excede 100 caracteres.')
        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        cleaned = [
            {
                'food': item['food'].strip(),
                'alternatives': [a.strip() for a in item['alternatives']
                                 if isinstance(a, str) and a.strip()],
            }
            for item in substitutions
        ]

        # Relê o JSON sob lock: evita perder uma regeneração/undo concorrente
        with transaction.atomic():
            diet_plan = DietPlan.objects.select_for_update().get(pk=pk, user=request.user)
            raw = dict(diet_plan.raw_response or {})
            raw['substitutions'] = cleaned
            diet_plan.raw_response = raw
            diet_plan.save(update_fields=['raw_response'])

        return Response({'substitutions': cleaned}, status=status.HTTP_200_OK)


class DietPDFAPIView(APIView):
    """
    GET /api/v1/diet/<id>/pdf
    Gera e retorna o plano alimentar em formato PDF.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            diet_plan = (
                DietPlan.objects
                .select_related('user', 'anamnese')
                .prefetch_related('meals')
                .get(pk=pk, user=request.user)
            )
        except DietPlan.DoesNotExist:
            return Response(
                {'error': 'Plano alimentar não encontrado.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            pdf_bytes = generate_diet_pdf(diet_plan)
        except Exception:
            logger.exception('Erro ao gerar PDF para DietPlan#%s', pk)
            return Response(
                {'error': 'Não foi possível gerar o PDF. Tente novamente.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        date_str  = timezone.localtime(diet_plan.created_at).strftime('%Y-%m-%d') if diet_plan.created_at else 'dieta'
        filename  = f'mynutri-dieta-{date_str}.pdf'

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Cache-Control'] = 'no-store'
        return response


def _regen_error_message(exc: Exception) -> str:
    """Mensagem amigável para falhas de regeneração (nunca expõe str(exc) da IA)."""
    from .services import AllergenViolation, NutritionDataGap

    if isinstance(exc, AllergenViolation):
        return (
            'A nova sugestão continha alimentos incompatíveis com suas alergias. '
            'Tente novamente ou descreva melhor o que deseja.'
        )
    if isinstance(exc, NutritionDataGap):
        return (
            'Não conseguimos calcular as calorias da nova sugestão com segurança. '
            'Tente novamente usando alimentos mais comuns.'
        )
    if isinstance(exc, TransientAIError):
        return 'O serviço de IA está instável no momento. Tente novamente em instantes.'
    return 'Não foi possível regenerar esta refeição. Tente novamente.'


class MealRegenerateAPIView(APIView):
    """
    PATCH /api/v1/diet/<diet_pk>/meal/<meal_pk>/regenerate
    Regenera pontualmente uma refeição sem alterar as demais do plano.

    Body (opcional): { "reason": "não gostei dos alimentos" }

    Resposta: dados atualizados da refeição + meals_raw_entry + macros totais.

    Limites:
      - MEAL_REGEN_DAILY_LIMIT regenerações por dia local por DietPlan, contando
        também as desfeitas (regenerar + desfazer não "devolve" a cota)
      - Usuário só pode regenerar refeições do seu próprio plano

    Concorrência (em 3 fases para não segurar lock durante a chamada à IA):
      1. Sob lock do DietPlan: confere a cota e RESERVA uma vaga criando o
         MealRegenerationLog (com is_undone=True = "reserva pendente", invisível
         para o undo). Duas requisições simultâneas não passam do limite.
      2. Sem lock: chama a IA. Se falhar, a reserva é apagada (cota devolvida).
      3. Sob lock: relê raw_response (pode ter mudado), aplica a nova refeição,
         grava o estado anterior REAL no log e o ativa (is_undone=False).
    """

    permission_classes = [IsAuthenticated]
    DAILY_LIMIT = MEAL_REGEN_DAILY_LIMIT

    def patch(self, request, diet_pk, meal_pk):
        # ── Validações baratas (antes de qualquer lock) ───────────────────────
        reason = request.data.get('reason') or ''
        if not isinstance(reason, str):
            return Response(
                {'error': '"reason" deve ser um texto.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        reason = reason.strip()
        if len(reason) > 300:
            return Response(
                {'error': '"reason" não pode exceder 300 caracteres.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_free_text(reason, 'Motivo')
        except drf_serializers.ValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) and exc.detail else exc.detail
            return Response({'error': str(detail)}, status=status.HTTP_400_BAD_REQUEST)

        # ── Fase 1: lock + cota + reserva ────────────────────────────────────
        with transaction.atomic():
            try:
                diet_plan = (
                    DietPlan.objects
                    .select_for_update()
                    .select_related('anamnese')
                    .get(pk=diet_pk, user=request.user)
                )
            except DietPlan.DoesNotExist:
                return Response(
                    {'error': 'Plano alimentar não encontrado.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                meal = Meal.objects.get(pk=meal_pk, diet_plan=diet_plan)
            except Meal.DoesNotExist:
                return Response(
                    {'error': 'Refeição não encontrada neste plano.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            used_today = _regenerations_used_today(diet_plan.pk)
            if used_today >= self.DAILY_LIMIT:
                return Response(
                    {
                        'error': (
                            f'Limite de {self.DAILY_LIMIT} regenerações por dia atingido '
                            'para este plano. Tente novamente amanhã.'
                        ),
                        'regenerations_remaining': 0,
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            if not diet_plan.anamnese_id:
                return Response(
                    {'error': 'Não é possível regenerar: plano sem anamnese associada.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            meals_raw = (diet_plan.raw_response or {}).get('meals', [])
            meal_index = meal.order
            if not (0 <= meal_index < len(meals_raw)):
                return Response(
                    {'error': 'Índice de refeição desatualizado. Recarregue a página.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Reserva a vaga na cota. is_undone=True mantém a reserva fora do
            # alcance do undo até a regeneração ser efetivamente aplicada.
            log = MealRegenerationLog.objects.create(
                diet_plan=diet_plan,
                meal=meal,
                user=request.user,
                reason=reason,
                previous_description=meal.description,
                previous_calories=meal.calories,
                previous_raw_meal=meals_raw[meal_index],
                is_undone=True,
            )

        # ── Fase 2: chamada à IA (sem lock) ──────────────────────────────────
        from .services import AIService

        try:
            result = AIService().regenerate_meal(diet_plan, meal_index, reason)
        except (ValueError, DietGenerationError) as exc:
            log.delete()
            logger.warning(
                'Regeneração da refeição %d do DietPlan#%s falhou: %s: %s',
                meal_index, diet_plan.pk, type(exc).__name__, exc,
            )
            # TransientAIError "puro" = API/rede instável (503); subclasses
            # (alergia, cobertura, macros) e demais erros = sugestão inválida (400)
            http_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if type(exc) is TransientAIError
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({'error': _regen_error_message(exc)}, status=http_status)
        except Exception:
            log.delete()
            logger.exception(
                'Erro ao regenerar refeição %d do DietPlan#%d', meal_index, diet_plan.pk
            )
            return Response(
                {'error': 'Falha ao regenerar a refeição. Tente novamente.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ── Fase 3: aplica sob lock, relendo o estado atual ──────────────────
        from .substitutions import generate_meal_substitutions
        from .services import _parse_allergens

        with transaction.atomic():
            try:
                diet_plan = (
                    DietPlan.objects
                    .select_for_update()
                    .select_related('anamnese')
                    .get(pk=diet_plan.pk)
                )
                meal = Meal.objects.get(pk=meal.pk, diet_plan=diet_plan)
            except (DietPlan.DoesNotExist, Meal.DoesNotExist):
                # Plano/refeição apagados durante a chamada à IA (o log cai em cascata)
                return Response(
                    {'error': 'Plano alimentar não encontrado.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            raw_copy = dict(diet_plan.raw_response or {})
            meals_copy = list(raw_copy.get('meals', []))

            if not (0 <= meal_index < len(meals_copy)):
                log.delete()
                return Response(
                    {'error': 'O plano foi alterado durante a regeneração. Recarregue a página.'},
                    status=status.HTTP_409_CONFLICT,
                )

            # Estado anterior REAL (pode ter mudado desde a fase 1, ex.: undo concorrente)
            log.previous_description = meal.description
            log.previous_calories = meal.calories
            log.previous_raw_meal = meals_copy[meal_index]
            log.is_undone = False
            log.save(update_fields=[
                'previous_description', 'previous_calories', 'previous_raw_meal', 'is_undone',
            ])

            meal.meal_name   = result['new_meal_name']
            meal.description = result['new_description']
            meal.calories    = result['new_calories']
            meal.save(update_fields=['meal_name', 'description', 'calories'])

            meals_copy[meal_index] = result['new_raw_meal']
            raw_copy['meals'] = meals_copy
            total_cal = _recalculate_plan_totals(raw_copy)

            # Regenera substituições contextuais com o plano atualizado
            allergens_list = _parse_allergens(
                (diet_plan.anamnese.allergies or '') if diet_plan.anamnese else ''
            )
            raw_copy['substitutions'] = generate_meal_substitutions(meals_copy, allergens_list)

            diet_plan.raw_response   = raw_copy
            diet_plan.total_calories = total_cal
            diet_plan.save(update_fields=['raw_response', 'total_calories'])

            remaining = regenerations_remaining_today(diet_plan.pk)

        return Response(
            {
                'meal': {
                    'id':          meal.pk,
                    'meal_name':   meal.meal_name,
                    'description': meal.description,
                    'calories':    meal.calories,
                    'order':       meal.order,
                },
                'meals_raw_entry':         result['new_raw_meal'],
                'macros':                  raw_copy['macros'],
                'total_calories':          total_cal,
                'log_id':                  log.pk,
                'regenerations_remaining': remaining,
            },
            status=status.HTTP_200_OK,
        )


class MealUndoAPIView(APIView):
    """
    POST /api/v1/diet/<diet_pk>/meal/<meal_pk>/undo
    Desfaz a última regeneração de uma refeição, restaurando o estado anterior.
    Não devolve a cota diária de regenerações.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, diet_pk, meal_pk):
        with transaction.atomic():
            try:
                diet_plan = (
                    DietPlan.objects
                    .select_for_update()
                    .get(pk=diet_pk, user=request.user)
                )
            except DietPlan.DoesNotExist:
                return Response(
                    {'error': 'Plano alimentar não encontrado.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                meal = Meal.objects.get(pk=meal_pk, diet_plan=diet_plan)
            except Meal.DoesNotExist:
                return Response(
                    {'error': 'Refeição não encontrada neste plano.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Última regeneração aplicada e não desfeita desta refeição
            last_log = (
                MealRegenerationLog.objects
                .filter(diet_plan=diet_plan, meal=meal, is_undone=False)
                .order_by('-created_at', '-pk')
                .first()
            )

            if not last_log:
                return Response(
                    {'error': 'Nenhuma regeneração disponível para desfazer.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── Restaura Meal ─────────────────────────────────────────────────
            prev_raw = last_log.previous_raw_meal or {}
            time_sug  = prev_raw.get('time_suggestion', '')
            meal_name = prev_raw.get('name', meal.meal_name)
            meal.meal_name   = f'{meal_name} ({time_sug})' if time_sug else meal_name
            meal.description = last_log.previous_description
            meal.calories    = last_log.previous_calories
            meal.save(update_fields=['meal_name', 'description', 'calories'])

            # ── Restaura raw_response (relido sob lock) ───────────────────────
            raw_copy = dict(diet_plan.raw_response or {})
            meals_copy = list(raw_copy.get('meals', []))
            meal_index = meal.order

            if 0 <= meal_index < len(meals_copy):
                meals_copy[meal_index] = prev_raw
                raw_copy['meals'] = meals_copy
                total_cal = _recalculate_plan_totals(raw_copy)
                diet_plan.raw_response   = raw_copy
                diet_plan.total_calories = total_cal
                diet_plan.save(update_fields=['raw_response', 'total_calories'])

            # Marca o log como desfeito (mantém para auditoria e para a cota)
            last_log.is_undone = True
            last_log.save(update_fields=['is_undone'])

            remaining = regenerations_remaining_today(diet_plan.pk)

        return Response(
            {
                'meal': {
                    'id':          meal.pk,
                    'meal_name':   meal.meal_name,
                    'description': meal.description,
                    'calories':    meal.calories,
                    'order':       meal.order,
                },
                'meals_raw_entry':         prev_raw,
                'macros':                  raw_copy.get('macros'),
                'total_calories':          raw_copy.get('calories'),
                'regenerations_remaining': remaining,
            },
            status=status.HTTP_200_OK,
        )
