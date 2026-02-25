def get_user_type(user):
    """
    Identifica o tipo de usuário baseado no model vinculado
    """
    if not user.is_authenticated:
        return None
    
    # Admin sempre é admin
    if user.groups.filter(name='Administrador').exists() or user.is_superuser:
        return 'admin'
    
    # Verificar TecnicoCampo (DEVE VIR PRIMEIRO!)
    try:
        if hasattr(user, 'tecnico') and user.tecnico is not None:
            return 'tecnico'
    except:
        pass
    
    # Verificar Colaborador SAC
    try:
        if hasattr(user, 'colaborador') and user.colaborador is not None:
            return 'colaborador'
    except:
        pass
    
    return None


def is_tecnico(user):
    """Verifica se é técnico de campo"""
    return get_user_type(user) == 'tecnico'


def is_colaborador_sac(user):
    """Verifica se é colaborador SAC"""
    return get_user_type(user) == 'colaborador'