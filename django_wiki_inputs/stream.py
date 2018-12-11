from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json
import pathlib

from . import misc
from . import fn
from . import models

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()

def input_to_dict(val):
    out = json.loads(val.val)
    out['pk'] = val.pk
    out['created'] = val.created.isoformat()
    out['author'] = None if val.author is None else val.author.username

    return out


@database_sync_to_async
def db_get_input(article, name, user, curr_pk=None):
    val = models.Input.objects.filter(
        article=article,
        owner=user,
        name=name).latest()

    if curr_pk == val.pk:
        return None

    return input_to_dict(val)



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
async def read_field(ic, user, path):
    name = path.name

    md = await misc.get_markdown_factory().get_markdown(path.parent, ic.user)
    if not md:
        yield {'type': 'error', 'val': f"{path.parent}: article does not exits"}
        return

    if not md.article.can_read(ic.user):
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

    curr = {
        'type': field['args']['type'],
        'pk': None,
        'created': None,
        'author': None,
        'val': field['args'].get('default'),
    }

    if not field.get('can_read', True):
        yield curr
        return

    while True:
        if field['args'].get('dummy', False):
            if ic.md == md:
                curr = ic.dummy_val.get(name, curr)
        else:
            try:
                c = await db_get_input(md.article, name, user, curr['pk'])
                if c is not None:
                    curr = c
            except models.Input.DoesNotExist:
                pass

        yield curr

        async with field['cv']:
            await field['cv'].wait()


async def arg_stream(ic, user, arg):
    if type(arg) in [int, str, float]:
        return stream.just({'type': type(arg).__name__, 'val': arg})

    elif isinstance(arg, pathlib.Path):
        path = misc.normpath(ic, arg)
        return read_field(ic, user, path)

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

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield item


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
    restart = True

    while restart:
        restart = False
        src = [await arg_stream(ic, owner, pathlib.Path(field['name']))]

        if 'owner' in field['args']:
            src.append(await arg_stream(ic, ic.user, field['args']['owner']))

        s = stream.ziplatest(*src, partial=False)
        last = None

        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if 'owner' in field['args']:
                    if i[1] is None:
                        continue

                    o = i[1]['val']
                    if o.pk != owner.pk:
                        owner = o
                        restart = True
                        break

                out = dict(type='input', id=idx, disabled=True)
                out['owner'] = None if ic.user == owner else owner.username
                out['val'] = '' if i[0] is None or i[0]['val'] is None else str(i[0]['val'])
                out['disabled'] = not field['can_write']

                if last == out:
                    continue
                last = out

                if field['args']['type'] in ['file', 'files', 'select-user']:
                    out['val'] = None

                if i[0] is not None and field['args']['type'] != i[0]['type']:
                    logger.warning(f"field type error: {field['args']['type']} != {i[0]['type']}")

                yield out
