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
    async def connect(self, *args, **kwargs):
        self.user = self.scope['user']
        if self.user.is_authenticated == False:
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

        if self.preview:
            await self.accept()
            return

        try:
            self.md = await misc.markdown_factory.get_markdown(self.path, self.user)
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
        self.run_task = asyncio.create_task(self.run())

        await self.accept()


    async def run(self):
        try:
            async with self.stream.stream() as s:
                async for msg in s:
                    logger.debug(f"{self.user}@{self.path}: send {{:.60s}} ...".format(' '.join(str(msg).split())))
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


    async def receive_json(self, content):
        try:
            idx = int(content['id'])
            field = self.md.input_fields[idx]
            val = content['val']
            owner = content.get('owner', self.user)
        except Exception:
            logger.warning(f"{self.user}@{self.path}: broken request {content!r}")
            return

        if field['cmd'] != 'input':
            logger.warning(f"{self.user}@{self.path}: broken request {content!r}")
            return

        await db_update_input(self.md.article, field['name'], self.user, owner, val)
        async with field['cv']:
            field['cv'].notify_all()
