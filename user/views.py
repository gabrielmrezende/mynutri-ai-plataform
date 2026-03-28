from django.shortcuts import render, redirect
from django.views.generic import CreateView
from django.urls import reverse_lazy
from django.contrib.auth import login
from .forms import CustomUserCreationForm

class RegisterView(CreateView):
    form_class = CustomUserCreationForm
    template_name = 'user/register.html'
    success_url = reverse_lazy('user:login')

    def form_valid(self, form):
        # Opcional: já logar o usuário automaticamente após o cadastro
        user = form.save()
        login(self.request, user)
        return redirect('questionario') # Redireciona para o questionário após cadastro
