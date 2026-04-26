import logging

from django.http import HttpResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

from .models import Anamnese, DietJob, DietPlan
from .serializers import AnamneseSerializer, DietPlanSerializer, DietPlanSummarySerializer
from .tasks import generate_diet_task
from .pdf_generator import generate_diet_pdf

logger = logging.getLogger(__name__)


class AnamneseAPIView(APIView):
    """
    POST /api/anamnese
    Salva as respostas do questionário nutricional do usuário logado.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

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


class DietGenerateAPIView(APIView):
    """
    POST /api/v1/diet/generate
    Enfileira a geração de dieta via Celery e retorna imediatamente com o job_id.

    Fluxo assíncrono:
        1. Cria DietJob(status='pending')
        2. Enfileira generate_diet_task via Celery
        3. Retorna 202 Accepted + {"job_id": <id>}
        4. Frontend faz polling em GET /api/v1/diet/status/<job_id>

    Modo síncrono (dev sem Redis / CELERY_TASK_ALWAYS_EAGER=True):
        O Celery executa a task inline antes de retornar — o job já estará
        'done' ou 'failed' na primeira chamada de polling.

    Requer: Authorization: Bearer <token>
    Limite: 3 gerações por dia por usuário.
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

        # Bloqueia se já houver um job em andamento para este usuário
        in_progress = DietJob.objects.filter(
            user=request.user,
            status__in=[DietJob.STATUS_PENDING, DietJob.STATUS_PROCESSING],
        ).first()
        if in_progress:
            return Response(
                {'job_id': in_progress.pk, 'status': in_progress.status},
                status=status.HTTP_202_ACCEPTED,
            )

        job = DietJob.objects.create(user=request.user, anamnese=anamnese)

        # delay() enfileira no Redis (prod) ou executa inline (dev com always_eager)
        generate_diet_task.delay(job.pk)

        logger.info('DietJob#%s criado para usuário %s.', job.pk, request.user.id)

        return Response({'job_id': job.pk, 'status': job.status}, status=status.HTTP_202_ACCEPTED)


class DietJobStatusAPIView(APIView):
    """
    GET /api/v1/diet/status/<job_id>
    Retorna o estado atual de um job de geração de dieta.

    Resposta:
        pending/processing: {"status": "...", "diet_plan_id": null}
        done:               {"status": "done", "diet_plan_id": <id>}
        failed:             {"status": "failed", "error": "<mensagem>"}

    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        try:
            job = DietJob.objects.get(pk=job_id, user=request.user)
        except DietJob.DoesNotExist:
            return Response({'error': 'Job não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        payload = {'status': job.status, 'diet_plan_id': None}

        if job.status == DietJob.STATUS_DONE and job.diet_plan_id:
            payload['diet_plan_id'] = job.diet_plan_id

        if job.status == DietJob.STATUS_FAILED:
            payload['error'] = job.error_message or 'Falha ao gerar dieta. Tente novamente.'

        return Response(payload, status=status.HTTP_200_OK)


class DietAPIView(APIView):
    """
    GET /api/diet
    Retorna o plano alimentar mais recente do usuário logado.
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

        return Response(DietPlanSerializer(diet_plan).data, status=status.HTTP_200_OK)


class DietListAPIView(APIView):
    """
    GET /api/v1/diet/list
    Retorna o histórico completo de planos alimentares do usuário logado,
    ordenado do mais recente para o mais antigo.
    Requer: Authorization: Bearer <token>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        diet_plans = (
            DietPlan.objects.filter(user=request.user)
            .order_by('-created_at')
        )
        serializer = DietPlanSummarySerializer(diet_plans, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DietDetailAPIView(APIView):
    """
    GET /api/v1/diet/<id>
    Retorna um plano alimentar específico do usuário logado pelo ID.
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

        return Response(DietPlanSerializer(diet_plan).data, status=status.HTTP_200_OK)


class DietSubstitutionsAPIView(APIView):
    """
    PATCH /api/v1/diet/<id>/substitutions
    Substitui a lista de substituições de um DietPlan do usuário autenticado.
    Body: { "substitutions": [{ "food": "...", "alternatives": ["...", ...] }] }
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            diet_plan = DietPlan.objects.get(pk=pk, user=request.user)
        except DietPlan.DoesNotExist:
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
            food = (item.get('food') or '').strip()
            alts = item.get('alternatives')
            if not food:
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
                DietPlan.objects.prefetch_related('meals')
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

        date_str  = diet_plan.created_at.strftime('%Y-%m-%d') if diet_plan.created_at else 'dieta'
        filename  = f'mynutri-dieta-{date_str}.pdf'

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
