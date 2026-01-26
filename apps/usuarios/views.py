from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard(request):
    if request.user.groups.filter(name='Administrador').exists():
        return render(request, 'dashboard/admin.html')
    
    return render(request, 'dashboard/colaborador.html')

