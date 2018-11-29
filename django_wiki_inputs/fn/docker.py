import io
import os
import tarfile
import aiodocker
import asyncio
from aiostream import core, stream
from .. import misc
from .. import stream as my_stream
import logging
import json
import aiohttp
import pathlib
import re
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.db import models


import ipdb  # NOQA

logger = logging.getLogger(__name__)

wi_native_re = re.compile(r'^#\s*WI[_-]NATIVE\s*(.*)$')

class MyException(Exception):
    pass


async def send_item(ws, con, aout, item):
    try:
        out = json.dumps(item)
    except TypeError:
        if isinstance(item[1]['val'], models.Model):
            item = (item[0], item[1].copy())
            item[1]['model'] = str(item[1]['val']._meta)
            item[1]['val'] = item[1]['val'].pk

        out = json.dumps(item)

    if aout.get(item[0], None) == out:
        return

    logger.debug(f"{con['id'][:12]}: < {out[:120]}")
    aout[item[0]] = out

    await ws.send_str(out + "\n")


async def get_dockerfile(dapi, md, path, user):
    obj = io.BytesIO()
    tar = tarfile.TarFile(fileobj=obj, mode="w")
    dfile = list()

    if str(path) == "/":
        dfile.append("FROM jenda1/testovadlo")
    else:
        dfile.append("FROM " + await get_image(dapi, path.parent, user))

    dst_path = "/wikilt" + str(path)
    for fn, item in md.source_fields.items():
        fn = fn.replace('"', '_')
        dst = dst_path + "/" + fn

        ti = tarfile.TarInfo(name=f"wi.{fn}")

        if 'type' in item and item['type'] in ['wiki_inputs', 'wiki-inputs', 'wi']:
            content = render_to_string("wiki/plugins/inputs/docker_wi_task", context={'text': item['text']}).encode('utf-8')
            ti.mode = 0o777
        elif 'type' in item and item['type'] in ['bash', 'shell']:
            content = ("#!/bin/bash\n\n" + item['text']).encode('utf-8')
            ti.mode = 0o777
        else:
            content = item['text'].encode('utf-8')

        dfile.append(f"COPY [\"{ti.name}\", \"{dst}\"]")

        ti.size = len(content)
        tar.addfile(ti, io.BytesIO(content))

    dfile.append(f"ENV PATH {dst_path}:$PATH")
    dfile.append(f"ENV WI_HOME {dst_path}")

    logger.debug("\n\t" + "\n\t".join(dfile))

    content = "\n".join(dfile).encode('utf-8')
    ti = tarfile.TarInfo(name="Dockerfile")
    ti.size = len(content)
    tar.addfile(ti, io.BytesIO(content))

    tar.close()
    obj.seek(0)

    return obj


async def get_image(dapi, path, user):
    md = await misc.get_markdown_factory().get_markdown(str(path), user)
    if md is None:
        raise MyException(f"{path}@{user}: does not exists")

    if str(path) == '/':
        image_tag = f"wikilt:{md.article.current_revision.pk}"
    else:
        image_tag = f"wikilt{path!s}:{md.article.current_revision.pk}"


    try:
        await dapi.images.inspect(image_tag)
        logger.debug(f"{path}@{user}: re-use container {image_tag}")
        return image_tag
    except aiodocker.exceptions.DockerError as e:
        if e.status != 404:
            raise e

    log = list()

    tar = await get_dockerfile(dapi, md, path, user)
    logger.debug(f"{path}@{user}: build {image_tag}")

    try:
        for i in await dapi.images.build(fileobj=tar, tag=image_tag, labels={'django.wiki.inputs': '1'}, encoding="identity"):
            if 'stream' in i:
                log.append("\t"+i['stream'].strip())
    except Exception:
        logger.debug(f"{path}@{user}: docker build failed:\n" + "\n".join(log))
        raise
    finally:
        tar.close()

    return image_tag

async def get_container(dapi, path, user):
    if not hasattr(get_container, "_lock"):
        get_container._lock = asyncio.Lock()

    async with get_container._lock:
        config = {"Image": await get_image(dapi, path, user),
                  "AttachStdin": True,
                  "AttachStdout": True,
                  "AttachStderr": True,
                  "Tty": False,
                  "OpenStdin": True,
                  "StdinOnce": True,
                  }

        return await dapi.containers.create(config=config)


@core.operator
async def websocket_reader(ws):
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            m = msg.data.rstrip()
        elif msg.type == aiohttp.WSMsgType.BINARY:
            m = msg.data.decode('utf8').rstrip()
        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"container error: {msg.data}")
            break

        try:
            for l in m.splitlines():
                yield ('ws', l)
        except json.JSONDecodeError:
            logger.warning("malformed msg from container:\n\t" + "\n\t".join(m.splitlines()))
            yield ('err', "⚠ malformed msg from container ⚠")


@core.operator
async def stream_enum(n, s):
    async with core.streamcontext(s) as streamer:
        async for i in streamer:
            yield (n, i)



@core.operator  # NOQA
async def docker(ic, args):
    if len(args) < 1:
        yield None
        return

    if not isinstance(args[0], pathlib.Path):
        yield ('err', "⚠ wrong first argument format ⚠")
        return

    docker_path = pathlib.Path(os.path.normpath(ic.path/args[0]))

    dapi = None
    try:
        dapi = aiodocker.Docker()
        con = await get_container(dapi, docker_path, ic.user)
        if con is None:
            return

        logger.debug(f"{con['id'][:12]}: created")

        ain = dict()
        aout = dict()
        for n, arg in enumerate(args[1:]):
            ain[n+1] = stream_enum(n+1, await my_stream.arg_stream(ic, ic.user, arg))

        ws = await con.websocket(stdin=True, stdout=True, stderr=True, stream=True)
        await con.start()

        logger.debug(f"{con['id'][:12]}: started")

        try:
            restart = True
            while restart:
                restart = False

                if ain:
                    s = stream.merge(*list(ain.values()), websocket_reader(ws))
                else:
                    s = stream.merge(websocket_reader(ws))

                    # if input is empty, send empty message to container
                    logger.debug(f"{con['id'][:12]}: < []")
                    await ws.send_str(json.dumps(list())+"\n")

                out = list()
                async with core.streamcontext(s) as streamer:
                    async for item in streamer:
                        if item[0] == 'ws':
                            logger.debug(f"{con['id'][:12]}: > {item[1][:120]}")

                            m = wi_native_re.match(item[1])
                            if m:
                                try:
                                    msg = json.loads(m.group(1))
                                    if msg['type'] in ['getval']:
                                        if msg['id'] in ain:
                                            continue

                                        try:
                                            u = User.objects.get(pk=msg['user'])
                                        except User.DoesNotExist:
                                            u = ic.user

                                        arg = pathlib.Path(msg['val'])
                                        ain[msg['id']] = stream_enum(msg['id'], await my_stream.arg_stream(ic, u, arg))

                                        restart = True
                                        break
                                    elif msg['type'] in ['error']:
                                        yield msg
                                        break
                                    else:
                                        yield msg
                                except json.JSONDecodeError:
                                    pass

                            else:
                                out.append(item[1])
                                yield {'type': 'stdout', 'val': "\n".join(out)}

                        elif item[0] == 'err':
                            logger.debug(f"{con['id'][:12]}: !! " + ' '.join(str(item[1]).split())[:120])
                            yield {'type': 'error', 'val': item[1]}
                            break

                        else:
                            await send_item(ws, con, aout, item)

        finally:
            logger.debug(f"{con['id'][:12]}: delete")

            try:
                await con.kill()
                await con.delete()
                pass
            except Exception:
                pass

            ws.close()

    except MyException as e:
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}
    except aiodocker.exceptions.DockerError as e:
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}
    except Exception as e:
        logger.exception(e)
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}

    finally:
        if dapi:
            await dapi.close()
