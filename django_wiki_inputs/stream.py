from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json
import pathlib
import os

from . import misc
from . import fn
from . import models

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_is_user_in_group(user, name):
    return user.groups.filter(name=name).exists()


@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()


@database_sync_to_async
def db_get_input(article, name, uname, curr_pk=None):
    val = models.Input.objects.filter(
        article=article,
        owner__username=uname,
        name=name).latest()

    if curr_pk == val.pk:
        return None

    out = json.loads(val.val)
    out['pk'] = val.pk
    out['created'] = val.created.isoformat(),
    out['author'] = None if val.author is None else val.author.username,

    return out


async def can_read(md, user, field=None, is_owner=True):
    if not md.article.can_read(user):
        return False

    if md.article.current_revision.user.pk == user.pk:
        return True

    if field is None or is_owner:
        return True

    if 'can_read' not in field['args']:
        return False

    can_read = field['args']['can_read']
    if can_read == '_all_':
        return True

    # user is in the can_read group
    if can_read == '_':
        return await db_is_user_in_group(user, can_read.strip('_'))
    else:
        return can_read == user.username or can_read == user.email


def normpath(ic, path):
    return pathlib.Path(os.path.normpath(os.path.join(ic.path, str(path))))


# def get_field_wiki(ic, md):
#     if not await can_read(md, ic.user, is_owner=is_owner):
#   curr = {
#           'type': 'wiki',
#           'pk': md.article.current_revision.pk,
#           'created': md.article.owner.username,
#           'author': md.article.owner.username,
#           'val':md.article.current_revision.content
#       }
#
#       if just_actual:
#           yield curr
#       else:       # FIXME: whole article history
#           yield [curr]
#
#       return



@core.operator  # NOQA
async def read_field(ic, uname, path):
    name = path.name
    is_owner = (ic.user.username == uname)

    md = await misc.get_markdown_factory().get_markdown(path.parent, ic.user)
    if not md:
        yield {'type': 'error', 'val': "🚫?"}
        return

    if not await can_read(md, ic.user, is_owner=is_owner):
        yield {'type': 'error', 'val': "🚫"}
        return

    if name in md.source_fields:
        yield md.source_fields.get(name)
        return

    for field in md.input_fields:
        if field['cmd'] == 'input' and field['name'] == name:
            break
    else:
        yield None
        return

    if not can_read(md, ic.user, field, is_owner):
        yield {'type': 'error', 'val': "🚫"}
        return

    curr = {
        'type': field['args']['type'],
        'pk': None,
        'created': None,
        'author': None,
        'val': field['args'].get('default'),
    }

    while True:
        if field['args'].get('dummy', False):
            if ic.md == md:
                curr = ic.dummy_val.get(name, curr)
        else:
            try:
                curr = await db_get_input(md.article, name, uname, curr['pk'])
            except models.Input.DoesNotExist:
                pass

        yield curr

        async with field['cv']:
            await field['cv'].wait()



async def arg_stream(ic, uname, arg):
    if type(arg) in [int, str, float]:
        return stream.just({'type': type(arg).__name__, 'val': arg})

    elif isinstance(arg, pathlib.Path):
        path = normpath(ic, arg)
        return read_field(ic, uname, path)

    elif type(arg) is dict and 'fname' in arg:
        return display_fn(ic, arg)

    else:
        logger.warning(f"{ic.user}@{ic.path}: argument {arg}: unknow type")
        return stream.empty()


@core.operator
async def display_fn(ic, field):
    try:
        m = getattr(fn, field['fname'])
        fnc = getattr(m, field['fname'])

        source = fnc(ic, field['args'])
    except AttributeError:
        yield {'type': 'error', 'val': f"⚠ neznámá funkce {field['fname']}"}
        return

    try:
        async with core.streamcontext(source) as streamer:
            async for item in streamer:
                yield item
    finally:
        if field['fname']:
            logger.debug(f"{ic.user}@{ic.path}: finalize function {field['fname']}")
        else:
            logger.debug(f"{ic.user}@{ic.path}: finalize function pprint")


@core.operator
async def display(ic, idx):
    field = ic.md.input_fields[idx]
    if 'fn' in field:
        source = display_fn(ic, {'fname': 'pprint', 'args': [field['fn']]})
    elif 'path' in field:
        source = display_fn(ic, {'fname': 'pprint', 'args': [field['path']]})

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield {'type': 'display', 'id': idx, 'val': item}


@core.operator
async def input(ic, idx):
    field = ic.md.input_fields[idx]

    owner = ic.user

    while True:
        src = [await arg_stream(ic, owner.username, pathlib.Path(field['name']))]

        if 'owner' in field['args']:
            src.append(await arg_stream(ic, ic.user.username, field['args']['owner']))

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if 'owner' in field['args']:
                    if i[1] is None:
                        continue
                    else:
                        o = await misc.str_to_user(i[1]['val'])
                        o = o if o else ic.user

                    if o != owner:
                        owner = o
                        break

                out = dict(type='input', id=idx, disabled=True)
                out['owner'] = None if ic.user == owner else owner.username
                out['val'] = '' if i[0]['val'] is None else str(i[0]['val'])
                out['disabled'] = ic.md.article.current_revision.locked

                if field['args']['type'] in ['file', 'files', 'select']:
                    out['val'] = None

                if field['args']['type'] != i[0]['type']:
                    logger.warning(f"field type error: {field['args']['type']} != {i[0]['type']}")

                yield out
