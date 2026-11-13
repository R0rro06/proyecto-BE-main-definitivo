from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils.decorators import method_decorator
from django.utils.html import format_html_join
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters

from .forms import UsuarioChangeAdminForm, UsuarioCreationAdminForm
from .accounts import create_account, delete_account, update_account
from .models import Perfil, Progreso, Rol, Usuario


admin.site.unregister(Group)
admin.site.unregister(User)


class RowActionsMixin:
    actions = None

    def get_list_display(self, request):
        def row_actions(obj):
            opts = self.model._meta
            links = []
            if self.has_change_permission(request, obj):
                links.append((
                    reverse(
                        f'admin:{opts.app_label}_{opts.model_name}_change',
                        args=(obj.pk,),
                    ),
                    'Editar',
                ))
            if self.has_delete_permission(request, obj):
                links.append((
                    reverse(
                        f'admin:{opts.app_label}_{opts.model_name}_delete',
                        args=(obj.pk,),
                    ),
                    'Eliminar',
                ))
            return format_html_join(
                ' ',
                '<a class="button" href="{}">{}</a>',
                links,
            ) or '-'

        row_actions.short_description = 'Acciones'
        return (*super().get_list_display(request), row_actions)


@admin.register(Usuario)
class UsuarioAdmin(RowActionsMixin, admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'tipo_usuario')
    search_fields = ('username', 'email')
    list_filter = ('perfil__rol',)
    ordering = ('username',)
    @admin.display(description='Tipo')
    def tipo_usuario(self, obj):
        perfil = obj.perfil_set.select_related('rol').order_by('pk').first()
        return perfil.rol.nombre if perfil else 'Sin perfil'

    @method_decorator(sensitive_post_parameters(
        'password1', 'password2', 'new_password1', 'new_password2',
    ))
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_form(self, request, obj=None, change=False, **kwargs):
        kwargs['form'] = UsuarioChangeAdminForm if obj else UsuarioCreationAdminForm
        return super().get_form(request, obj, change, **kwargs)

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if change:
                update_account(obj, form.cleaned_data.get('new_password1'))
            else:
                create_account(obj, form.cleaned_data['password1'])
            rol = Rol.objects.get(codigo=form.cleaned_data['tipo'])
            Perfil.objects.update_or_create(usuario=obj, defaults={'rol': rol})

    def delete_model(self, request, obj):
        delete_account(obj)

    def get_deleted_objects(self, objs, request):
        # La baja de un usuario elimina sus perfiles y avances por CASCADE.
        # Esos modelos siguen protegidos contra el borrado directo en el Admin.
        deleted, counts, permissions, protected = super().get_deleted_objects(objs, request)
        cascade_names = {Perfil._meta.verbose_name, Progreso._meta.verbose_name}
        return deleted, counts, permissions - cascade_names, protected


@admin.register(Rol)
class RolAdmin(RowActionsMixin, admin.ModelAdmin):
    list_display = ('id', 'codigo', 'nombre')
    search_fields = ('codigo', 'nombre')
    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or (not obj.codigo and not obj.perfil_set.exists())
        )


@admin.register(Perfil)
class PerfilAdmin(RowActionsMixin, admin.ModelAdmin):
    list_display = ('id', 'usuario', 'rol')
    list_filter = ('rol',)
    search_fields = ('usuario__username',)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.usuario.username != 'admin'
        )

    def get_readonly_fields(self, request, obj=None):
        return ('usuario',) if obj else ()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'rol':
            kwargs['queryset'] = Rol.objects.exclude(codigo='administrador')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
