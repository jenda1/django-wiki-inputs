# -*- coding: utf-8 -*-
from django.contrib import admin

from . import models


@admin.register(models.Input)
class InputAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'article',
        'name',
        'created',
        'owner',
        'author',
        'val',
    )
    list_filter = ('article', 'created', 'owner', 'author')
    search_fields = ('name',)
