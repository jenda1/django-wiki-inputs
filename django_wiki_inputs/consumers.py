from channels.generic.websocket import AsyncJsonWebsocketConsumer
import logging
from wiki.models import URLPath
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from wiki.core.markdown import ArticleMarkdown
from django.db import transaction
from django.utils import timezone
import asyncio
import re
from . import models
import pathlib
import json

import ipdb # NOQA

logger = logging.getLogger(__name__)

preview_re = re.compile(r'^(.+/|)_preview/$')


class InputConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self, *args, **kwargs):
        self.user = self.scope['user']

        try:
            qs = parse_qs(self.scope['query_string'].decode())
        except Exception:
            await self.close()
            return

        if 'path' not in qs:
            await self.close()
            return

        self.path = pathlib.Path(qs['path'][0])
        self.preview = preview_re.match(str(self.path))

        if self.preview:
            await self.accept()
            return

        try:
            self.article = await self.db_get_article()
            if self.article is None:
                await self.accept()
                return

            self.md = ArticleMarkdown(self.article, user=self.user, preview=True)
            self.md.convert(self.article.current_revision.content)
        except Exception as e:
            await self.close()
            raise e

        await self.init_data()

        logger.info(f"{self.user}@{self.path}: accept")
        await self.accept()

        self.tasks = list()
        for idx, i in enumerate(self.md.input_fields):
            self.tasks.append(asyncio.create_task(self.send_field(idx)))

        logger.debug(f"{self.user}@{self.path}: listen {self.groups}")
        for g in self.groups:
            await self.channel_layer.group_add(g, self.channel_name)


    async def init_data(self):
        self.input = dict()
        self.display = dict()
        self.groups = set()

        for idx, field in enumerate(self.md.input_fields):
            if field['cmd'] == 'input':
                grps = [self.path_to_group(field['name'])]

                self.input[idx] = {
                    'name': field['name'],
                    'attr': field['attr'],
                    'curr': await self.db_get_input(field['name']),
                    'groups': grps,
                }

            elif field['cmd'] == 'display':
                if 'name' in field:
                    grps = [self.path_to_group(field['name'])]

                    self.display[idx] = {
                        'groups': grps,
                    }

                elif 'fn' in field:
                    grps = [self.path_to_group(p) for p in field['fn']['args'] if isinstance(p, pathlib.Path)]

                    self.display[idx] = {
                        'groups': grps
                    }
                else:
                    assert False

            else:
                assert False

            self.groups |= set(grps)


    def path_to_group(self, p):
        full = (self.path/p).resolve()
        return str(full).replace("/", ".")[1:]


    async def disconnect(self, close_code):
        if self.preview:
            return

        for g in self.groups:
            await self.channel_layer.group_discard(g, self.channel_name)

        n = 0
        for t in self.tasks:
            if not t.done():
                t.cancel()
                n += 1

        logger.info("{}@{}: disconnect{}".format(self.user, self.path, f", cancelling {n} tasks" if n > 0 else ""))



    @database_sync_to_async
    def db_get_article(self):
        p = URLPath.get_by_path(str(self.path), select_related=True)
        if p and p.article.can_read(self.user):
            return p.article


    @database_sync_to_async
    def db_get_input(self, name):
        return models.Input.objects.filter(
            article=self.article,
            owner=self.user,
            name=name,
            newer__isnull=True).last()


    @database_sync_to_async
    def db_update_input(self, inp, val):
        ts = timezone.now()

        with transaction.atomic():
            n = models.Input.objects.create(
                article=self.article,
                name=inp['name'],
                created=ts,
                owner=self.user,
                author=self.user,
                val=json.dumps(val))

            if inp['curr']:
                inp['curr'].newer = n
                inp['curr'].save()
                inp['curr'] = n


    async def send_field(self, idx):
        if idx in self.input:
            i = self.input[idx]
            content = dict(id=idx, val=i['curr'].val if i['curr'] else None)

            logger.debug(f"{self.user}@{self.path}: send {{:.60s}} ...".format(' '.join(str(content).split())))

            await self.send_json(content)


    async def input_update(self, event):
        logger.debug(f"{self.user}@{self.path}: input update {{:.60s}} ...".format(' '.join(str(event).split())))
        pass



    async def receive_json(self, content):
        try:
            inp = self.input[int(content['id'])]
            val = content['val']
        except Exception:
            logger.warning(f"{self.user}@{self.path}: broken request {content!r}")
            return

        if inp['curr'] and json.loads(inp['curr'].val) == val:
            logger.debug(f"{self.user}@{self.path}: no-update request {content!r}")
            return

        # FIXME: DoS protection - if too often, send just "resend-later" answer

        await self.db_update_input(inp, val)

        for g in inp['groups']:
            await self.channel_layer.group_send(
                g, {
                    "type": "input.update",
                })
