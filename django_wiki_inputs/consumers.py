from channels.generic.websocket import AsyncJsonWebsocketConsumer
import logging
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.db import transaction
from django.utils import timezone
import asyncio
import re
import pathlib
import json
from aiostream import stream
import magic
import base64

from . import stream as my_stream
from . import models
from . import misc
from .fn import * # NOQA

import ipdb # NOQA

logger = logging.getLogger(__name__)

preview_re = re.compile(r'^(.+/|)_preview/$')

@database_sync_to_async
def db_update_input(article, name, user, owner, val):
    val_json = json.dumps(val)
    ts = timezone.now()

    with transaction.atomic():
        old_qs = models.Input.objects.filter(
            article=article,
            name=name,
            owner=owner)

        if old_qs.exists():
            old = old_qs.latest()

            if old.val == val_json:
                return

            if ts <= old.created:
                logger.error(f"{user}@{article}/{name}: time error! ({ts} <= {old.created}")
                return

        n = models.Input.objects.create(
            article=article,
            name=name,
            created=ts,
            owner=owner,
            author=user,
            val=val_json)

    return n


class InputConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self, *args, **kwargs):  # NOQA
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return

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
        self.dummy_val = dict()

        if self.preview:
            await self.accept()
            return

        try:
            self.md = await misc.get_markdown_factory().get_markdown(self.path, self.user)
        except KeyError as e:
            await self.accept()
            return

        streams = list()
        for idx, field in enumerate(self.md.input_fields):
            if field['cmd'] == 'input':
                streams.append(my_stream.input(self, idx))

            elif field['cmd'] == 'display':
                streams.append(my_stream.display(self, idx))

            else:
                logger.error(f"{self.user}@{self.path}: unknown filed type {field['cmd']}")

        self.stream = stream.merge(*streams)

        # python 3.6 does not have create_task() yet
        # self.run_task = asyncio.create_task(self.run())
        self.run_task = asyncio.ensure_future(self.run())

        await self.accept()


    async def run(self):
        try:
            async with self.stream.stream() as s:
                async for msg in s:
                    logger.debug(f"{self.user}@{self.path}: send {{:.80s}} ...".format(' '.join(str(msg).split())))
                    await self.send_json(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(e, exc_info=True)
        finally:
            self.close()


    async def disconnect(self, close_code):
        if hasattr(self, 'run_task'):
            self.run_task.cancel()


    async def receive_json(self, content):  # NOQA
        try:
            idx = int(content['id'])
            field = self.md.input_fields[idx]
            val = content['val']
            owner = content.get('owner', self.user)
        except Exception:
            logger.warning(f"{self.user}@{self.path}: broken request")
            return

        if field['cmd'] != 'input':
            logger.warning(f"{self.user}@{self.path}: broken request ({field['cmd']} != input)")
            return

        if self.md.article.current_revision.locked:
            logger.info(f"{self.user}@{self.path}: article is locked")
            return

        owner = None
        if 'owner' in field['args']:
            o = field['args']['owner']

            if type(o) == str:
                owner = await misc.str_to_user(owner)

            elif type(o) == pathlib.PosixPath:
                v = self.dummy_val.get(str(o))
                if v:
                    owner = await misc.str_to_user(v['val'])

        if owner:
            logger.debug(f"get {field['name']}({idx}): {owner}@{field['args']['type']} {val}")
        else:
            logger.debug(f"get {field['name']}({idx}): {field['args']['type']} {val}")

        # verify files input
        try:
            if field['args']['type'] in ['file', 'files']:
                for i, x in enumerate(val):
                    buf = base64.b64decode(x['content'], validate=True)
                    m = magic.detect_from_content(buf)

                    if val[i]['type'] != m.mime_type:
                        if m.mime_type.startswith('text/') and val[i]['type'].startswith('text/'):
                            pass    # libmagic is not good in text format detection
                        else:
                            logger.warning(f"{self.user}@{self.path}: different mimetype ({val[i]['type']} != {m.mime_type})")
                            val[i]['type'] = m.mime_type

            elif field['args']['type'] in ['select']:
                val = field['args']['values'][int(val)]

        except Exception as e:
            logger.warning(f"{self.user}@{self.path}: broken request - {e}")
            return


        if field['args'].get('dummy', False):
            self.dummy_val[field['name']] = {'type': field['args']['type'], 'val': val}
        else:
            await db_update_input(self.md.article, field['name'], self.user,
                                  self.user if owner is None else owner,
                                  {'type': field['args']['type'], 'val': val})

        async with field['cv']:
            field['cv'].notify_all()
