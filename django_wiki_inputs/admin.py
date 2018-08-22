# -*- coding: utf-8 -*-
from django.contrib import admin

from . import models


@admin.register(Input)
class InputAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'article',
        'name',
        'created',
        'owner',
        'author',
        'val',
        'newer_pk',
    )
    list_filter = ('article', 'created', 'owner', 'author', 'newer')
    search_fields = ('name',)

    def newer_pk(self, obj):
        return obj.newer.pk if obj.newer else "None"
