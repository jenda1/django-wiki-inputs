from django.db import models
from django.utils.translation import ugettext_lazy as _
from wiki.models import Article
from django.contrib.auth.models import User

import logging


logger = logging.getLogger(__name__)


class Input(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, verbose_name=_('article'))
    name = models.CharField(max_length=28)

    created = models.DateTimeField()

    owner = models.ForeignKey(User, help_text='the owner of the input.', related_name='input_owner', on_delete=models.CASCADE)
    author = models.ForeignKey(User, help_text='the author of the input.', related_name='input_author', db_index=True, null=True, blank=True, on_delete=models.SET_NULL)

    val = models.TextField(blank=True, null=True)


    class Meta:
        verbose_name = _('Input')
        verbose_name_plural = _('Inputs')
        unique_together = ('article', 'name', 'owner', 'created')
        ordering = ['article', 'name', 'owner', 'created']
        get_latest_by = ['article', 'name', 'owner', 'created']



    def __str__(self):
        return '{}.{}{}:{:.60s}{}'.format(
            self.article,
            self.name,
            "" if self.owner is None else "@{}".format(self.owner),
            self.val,
            "..." if len(self.val) > 60 else "")
