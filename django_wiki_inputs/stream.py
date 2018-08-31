from django.contrib.auth.models import User, Group
from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json

from . import models
from . import misc

import ipdb # NOQA

logger = logging.getLogger(__name__)

@database_sync_to_async
def db_get_input(article, name, user):
    return models.Input.objects.filter(
        article=article,
        owner=user,
        name=name).last()


@database_sync_to_async
def db_get_user(name):
    try:
        return User.objects.get(username=name)
    except User.DoesNotExist:
        try:
            return User.objects.get(email=name)
        except User.DoesNotExist:
            return None


@database_sync_to_async
def db_get_group(name):
    try:
        return Group.objects.get(name=name)
    except User.DoesNotExist:
        return None


@database_sync_to_async
def db_is_user_in_group(user, grp):
    return user.groups.filter(name=grp.name).exists()


@database_sync_to_async
def db_get_input_grp(article, name, grp):
    if grp is True:
        logger.debug(models.Input.objects.filter(
            article=article,
            name=name).distinct(article, name, owner).query)
    else:
        logger.debug(models.Input.objects.filter(
            article=article,
            owner__group=grp,
            name=name).distinct(article, name, owner).query)


@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()


@core.operator  # NOQA
async def read_field(md, name, user, filt):
    for inp in md.input_fields:
        if inp['cmd'] == 'input' and inp['name'] == name:
            filt_usr = None
            filt_grp = None

            if filt is None:
                filt_usr = user
                break

            if 'can_read' in inp:
                val = inp['can_read']

                if val == '_all_':
                    filt_grp = True
                    break

                elif val[0] == '_':
                    filt_grp = await db_get_group(val.strip('_'))
                    if filt_grp and db_is_user_in_group(user, filt_grp):
                        break

                elif val == user.username or val == user.email or md.article.current_revision.user == user:
                    filt_usr = await db_get_user(val)
                    if filt_usr:
                        break

                # user has read permission to the field
                yield None
                return
    else:
        # FIXME: try other sources
        yield None
        return

    curr = None
    while True:
        if filt_usr:
            db_val = await db_get_input(md.article, name, filt_usr)
            if db_val is None:
                yield None

            elif curr and curr.pk == db_val.pk:
                continue
            else:
                yield json.loads(db_val.val)
                curr = db_val

        elif filt_grp:
            db_val = await db_get_input_grp(md.article, name, filt_grp)
            # FIXME: check curr == db_val

            yield {i.owner: json.loads(i.val) for i in db_val}

        async with inp['cv']:
            await inp['cv'].wait()


@core.operator
async def display(ic, idx):
    source = display_fn(ic.user, ic.path, ic.md.input_fields[idx]['fn'])

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield {'type': 'display',
                   'id': idx,
                   'val': " ".join([str(x) for x in item if x is not None])}


@core.operator
async def display_fn(user, path, field):
    args = list()
    # if fnc['fname'] is None:
    #    fnc = lambda x: x[0]
    # else:
    #    logger.warning(f"{self.user}@{self.path}: unknown fname {field['fname']}")
    #    return None

    for arg in field['args']:
        if type(arg) in [int, str, float]:
            args.append(stream.just(arg))

        elif type(arg) is dict and 'fname' in arg:
            args.append(display_fn(user, path, arg))

        elif type(arg) is dict and 'path' in arg:
            p = (path/arg['path']).resolve()
            md = await misc.markdown_factory.get_markdown(p.parent, user)
            if md is None:
                logger.debug(f"{user}@{path}: article {p.parent} does not exits or user has no read permission")
                args.append(stream.empty())
            else:
                args.append(read_field(md, p.name, user, arg.get('filter')))

        else:
            logger.warning(f"{user}@{path}: {field['src_']}: argument {arg}: unknow type")
            args.append(stream.empty)

    logger.debug("args:" + str(args))
    source = stream.ziplatest(*args)
    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            logger.debug("item:" + str(item))
            yield item


@core.operator
async def input(ic, idx):
    db_val = await db_get_input(ic.md.article, ic.md.input_fields[idx]['name'], ic.user)
    yield dict(type='input',
               id=idx,
               disabled=False,
               val=json.loads(db_val.val) if db_val else None)
