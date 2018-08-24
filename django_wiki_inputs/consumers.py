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
from collections import defaultdict
from django.contrib.auth.models import User, Group

from .fn import * # NOQA

import ipdb # NOQA

logger = logging.getLogger(__name__)

preview_re = re.compile(r'^(.+/|)_preview/$')


def can_read_input(inp, user):
    return True     # FIXME !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


class _MarkdownFactory(object):
    def __init__(self):
        self.cache = defaultdict(dict)

    async def get_markdown(self, path, user):
        article = await self.db_get_article(path)
        if article is None or not article.can_read(user):
            raise KeyError()

        try:
            md = self.cache[article.pk][user.pk]
            if md.article_revision_pk == article.current_revision.pk:
                return md
        except KeyError:
            pass

        logger.info(f"{user}@{path}: render current version")
        md = ArticleMarkdown(article, user=user, preview=True)
        md.convert(article.current_revision.content)
        md.article_revision_pk = article.current_revision.pk

        for inp in md.input_fields:
            logger.debug(f"{user}@{path}: {inp}")

        self.cache[article.pk][user.pk] = md

        return md


    async def get_field(self, root, path, user):
        path_full = (root/path['path']).resolve()
        md = await self.get_markdown(path_full.parent, user)

        if 'grp' in path:
            if not user.groups.filter(name=path['grp']).exists():
                raise KeyError()

        for inp in md.input_fields:
            if inp['cmd'] == 'input' and inp['name'] == path_full.name:
                if ('grp' in path or 'usr' in path) and not can_read_input(inp, user):
                    raise KeyError()

                if 'grp' in path:
                    grp = Group.objects.get(name=path['grp'])
                    return {i.owner: json.loads(i.val) for i in await self.db_get_input_grp(md.article, inp['name'], grp)}
                else:
                    usr = User.objects.get(username=path['usr']) if 'usr' in path else user
                    return await self.db_get_input_usr(md.article, inp['name'], usr)

        # FIXME: other sources



    @database_sync_to_async
    def db_get_input_usr(self, article, name, usr):
        return models.Input.objects.filter(
            article=article,
            name=name,
            owner=usr,
            newer__isnull=True).last()


    @database_sync_to_async
    def db_get_input_grp(self, article, name, grp):
        return models.Input.objects.filter(
            article=article,
            name=name,
            owner__groups__name=grp,
            newer__isnull=True)


    @database_sync_to_async
    def db_get_article(self, path):
        p = URLPath.get_by_path(str(path))

        return p.article if p else None



_markdown_factory = _MarkdownFactory()


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
            self.md = await _markdown_factory.get_markdown(self.path, self.user)
        except KeyError as e:
            await self.accept()
            return

        await self.init_data()
        await self.accept()

        self.tasks = list()
        for idx, i in enumerate(self.md.input_fields):
            self.tasks.append(asyncio.create_task(self.send_field(idx)))

        logger.debug(f"{self.user}@{self.path}: listen {self.groups}")
        for g in self.groups:
            await self.channel_layer.group_add(g, self.channel_name)


    def display_groups(self, fn):
        grps = set()

        for p in fn['args']:
            if type(p) is not dict:
                continue

            if 'path' in p:
                grps.add(self.path_to_group(p['path']))
            elif 'fname' in p:
                grps |= self.display_groups(p)

        return grps


    async def init_data(self):
        self.input = dict()
        self.display = dict()
        self.groups = set()

        for idx, field in enumerate(self.md.input_fields):
            if field['cmd'] == 'input':
                grps = set([self.path_to_group(field['name'])])

                self.input[idx] = {
                    'name': field['name'],
                    'attr': field['attr'],
                    'curr': await self.db_get_input(field['name']),
                    'groups': grps,
                }

            elif field['cmd'] == 'display':
                grps = self.display_groups(field['fn'])

                self.display[idx] = {
                    'fn': field['fn'],
                    'groups': grps,
                }

            else:
                assert False

            self.groups |= grps


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
    def db_get_input(self, name):
        return models.Input.objects.filter(
            article=self.md.article,
            owner=self.user,
            name=name,
            newer__isnull=True).last()


    @database_sync_to_async
    def db_update_input(self, inp, val):
        ts = timezone.now()

        with transaction.atomic():
            n = models.Input.objects.create(
                article=self.md.article,
                name=inp['name'],
                created=ts,
                owner=self.user,
                author=self.user,
                val=json.dumps(val))

            if inp['curr']:
                inp['curr'].newer = n
                inp['curr'].save()
                inp['curr'] = n


    async def display_value(self, field):
        args = list()

        if field['fname'] is None:
            fnc = lambda x: x[0]
        else:
            logger.warning(f"{self.user}@{self.path}: unknown fname {field['fname']}")
            return None


        for a in field['args']:
            if type(a) in [int, str, float]:
                args.append(a)

            elif type(a) is dict and 'fname' in a:
                args.append(await self.display_value(a))

            elif type(a) is dict and 'path' in a:
                try:
                    val = await _markdown_factory.get_field(self.path, a, self.user)
                except Exception as e:
                    val = None
                    logger.warning(f"{self.user}@{self.path}: get_field {a} fails ({e})")

                args.append(val)
            else:
                assert 1 == 0

        return fnc(args)




    async def send_field(self, idx):
        content = dict(id=idx)

        if idx in self.input:
            content['type'] = 'input'
            content['disabled'] = False

            if self.input[idx]['curr']:
                content['val'] = json.loads(self.input[idx]['curr'].val)

        elif idx in self.display:
            content['type'] = 'display'
            content['val'] = await self.display_value(self.display[idx]['fn'])

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
