#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import click
import datetime
import django
import json
import hashlib
from multiprocessing import Pool
import os
import mistune
import random
import re
import requests
import shutil
import sys
import time
from PIL import Image, ExifTags

from django.conf import settings
from django.template import Template, Context
from django.utils.text import slugify
from livereload import Server
from subprocess import call
from yaml import load, dump


BUILD_DIR = ".build"
CACHE_DIR = ".cache"
CACHE_FOREVER_DIR = "cf"
NUM_PARALLEL_THREADS = 4
ROOT_DIR = os.path.abspath(os.getcwd())
INK_DIR = os.path.abspath(os.path.dirname(__file__))
MEDIA_ROOTS = [os.path.join(BUILD_DIR,), os.path.join(ROOT_DIR, "static"),]
DEV_PORT = "5555"
IGNORE_FILES = [".DS_Store", ".git"]
pages = []
site_info = {}
private_site_info = {}
dev = False
static_url = ""
site_data_url = ""
facebook_profiles = []
twitter_profiles = []
COMBINED_FILENAMES_GENERATED = {}
FILENAMES_GENERATED = {}

markdown = mistune.Markdown()

CONFIG = None

# Site config.
if os.path.exists(os.path.join(ROOT_DIR, "site.yml")):
    with open(os.path.join(ROOT_DIR, "site.yml")) as f:
        CONFIG = load(f)

if CONFIG:
    if "url" not in CONFIG:
        raise AttributeError("Missing url in site")
    SITE_DIR_URL = CONFIG["url"].split("://")[1]


# from sys import path

# PROJECT_ROOT = abspath(join(dirname(__file__), "project"))
# path.insert(0, PROJECT_ROOT)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime) or isinstance(o, datetime.date):
            return o.isoformat()
        if isinstance(o, file):
            return ""

        return json.JSONEncoder.default(self, o)


def date_string_to_datetime(date_string):
    return datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M")

def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def combine_filenames(filenames, max_length=40):
    """Return a new filename to use as the combined file name for a
    bunch of files, based on the SHA of their contents.
    A precondition is that they all have the same file extension

    Given that the list of files can have different paths, we aim to use the
    most common path.

    Example:
      /somewhere/else/foo.js
      /somewhere/bar.js
      /somewhere/different/too/foobar.js
    The result will be
      /somewhere/148713695b4a4b9083e506086f061f9c.js

    Another thing to note, if the filenames have timestamps in them, combine
    them all and use the highest timestamp.

    """
    # Get the SHA for each file, then sha all the shas.

    path = None
    names = []
    extension = None
    timestamps = []
    shas = []
    filenames.sort()
    concat_names = "_".join(filenames)
    if concat_names in COMBINED_FILENAMES_GENERATED:
        return COMBINED_FILENAMES_GENERATED[concat_names]

    for filename in filenames:
        name = os.path.basename(filename)
        if not extension:
            extension = os.path.splitext(name)[1]
        elif os.path.splitext(name)[1] != extension:
            raise ValueError("Can't combine multiple file extensions")

        for base in MEDIA_ROOTS:
            try:
                shas.append(md5(os.path.join(base, filename)))
                break
            except IOError:
                pass


        if path is None:
            path = os.path.dirname(filename)
        else:
            if len(os.path.dirname(filename)) < len(path):
                path = os.path.dirname(filename)

    m = hashlib.md5()
    m.update(",".join(shas))

    new_filename = "%s-inkmd" % m.hexdigest()

    new_filename = new_filename[:max_length]
    new_filename += extension
    COMBINED_FILENAMES_GENERATED[concat_names] = new_filename

    return os.path.join(path, new_filename)

def filename_generator(file_parts, new_m_time=None):
    # print "filename_generator"
    # print file_parts
    concat = "".join(file_parts)
    if concat in FILENAMES_GENERATED:
        # print FILENAMES_GENERATED[concat]
        return FILENAMES_GENERATED[concat]
    
    sha = ""
    if "-inkmd" not in file_parts[0]:
        for base in MEDIA_ROOTS:
            try:
                sha = "%s-inkmd" % md5(os.path.join(base, concat))
                break
            except IOError:
                pass


    new_name = ''.join([file_parts[0], sha, file_parts[1]])
    FILENAMES_GENERATED[concat] = new_name
    # print new_name
    return new_name

def echo(str):
    click.echo(str)


def error(str):
    click.secho(str, fg="red")


def warn(str):
    click.secho(str, fg="yellow")

def flip_horizontal(im): return im.transpose(Image.FLIP_LEFT_RIGHT)
def flip_vertical(im): return im.transpose(Image.FLIP_TOP_BOTTOM)
def rotate_180(im): return im.transpose(Image.ROTATE_180)
def rotate_90(im): return im.transpose(Image.ROTATE_90)
def rotate_270(im): return im.transpose(Image.ROTATE_270)
def transpose(im): return rotate_90(flip_horizontal(im))
def transverse(im): return rotate_90(flip_vertical(im))
orientation_funcs = [None,
                 lambda x: x,
                 flip_horizontal,
                 rotate_180,
                 flip_vertical,
                 transpose,
                 rotate_270,
                 transverse,
                 rotate_90
                ]


def apply_orientation(im):
    """
    Extract the oritentation EXIF tag from the image, which should be a PIL Image instance,
    and if there is an orientation tag that would rotate the image, apply that rotation to
    the Image instance given to do an in-place rotation.

    :param Image im: Image instance to inspect
    :return: A possibly transposed image instance
    """

    try:
        kOrientationEXIFTag = 0x0112
        if hasattr(im, '_getexif'): # only present in JPEGs
            e = im._getexif()       # returns None if no EXIF data
            if e is not None:
                #log.info('EXIF data found: %r', e)
                orientation = e[kOrientationEXIFTag]
                f = orientation_funcs[orientation]
                return f(im)
    except:
        # We'd be here with an invalid orientation value or some random error?
        pass # log.exception("Error applying EXIF Orientation tag")
    return im


def generate_thumbs_and_resize(dirpath, filename, out_filename):
    # print("dirpath, filename, out_filename")
    # print(dirpath)
    # print(filename)
    # print(out_filename)
    valid_image = False
    try:
        original_image = Image.open(os.path.join(dirpath, filename))
        # do stuff
        original_image = apply_orientation(original_image)
        valid_image = True
    except IOError:
        # filename not an image file
        pass

    valid_operation = False
    if valid_image:
        # Yeah.  About that.  
        renamed_out = out_filename.split(".")
        hash_path = "/".join(renamed_out[-2].split("/")[1:])
        # out_hash = filename_generator([hash_path, ".%s" % renamed_out[-1]])
        # print(renamed_out)
        # print(out_hash)
        # renamed_out[-2] = "%s%s-%%s" % (renamed_out[-2], out_hash.split("/")[-1])
        renamed_out[-2] = "%s-%%s" % renamed_out[-2]
        # print(renamed_out)
        renamed_out = ".".join(renamed_out)
        # renamed_out = renamed_out.replace(BUILD_DIR, "%s/%s" % (BUILD_DIR, CACHE_FOREVER_DIR))
        # print(renamed_out)
        orig_width, orig_height = original_image.size

        # make thumbs
        if "width" in CONFIG["images"]["thumbs"]:
            for width in CONFIG["images"]["thumbs"]["width"]:
                thumb_out = renamed_out % ("%sw" % width)
                # print(thumb_out)
                im = original_image.copy()
                size = width, orig_height * (float(width) / orig_width)
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=85)

        if "height" in CONFIG["images"]["thumbs"]:
            for height in CONFIG["images"]["thumbs"]["height"]:
                thumb_out = renamed_out % ("%sh" % height)
                # print(thumb_out)
                im = original_image.copy()
                size = orig_width * (float(height) / orig_height), height
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=85)

        # resize source to max.
        if "max" in CONFIG["images"]:
            if "width" in CONFIG["images"]["max"]:
                width = CONFIG["images"]["max"]["width"]
                # print("Resizing to %s" % width)
                if orig_width > width:
                    size = width, orig_height * (float(width) / orig_width)
                    # print(size)
                    im = original_image.copy()
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=85)
                    valid_operation = True

            if "height" in CONFIG["images"]["max"]:
                height = CONFIG["images"]["max"]["height"]
                if orig_height > height:
                    im = original_image.copy()
                    size = orig_width * (float(height) / orig_height), height
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=85)
                    valid_operation = True

    return valid_operation


def modification_date(filename):
    t = os.path.getmtime(filename)
    return datetime.datetime.fromtimestamp(t)


def is_newer(dirpath, filename):
    # check against cache.
    cache_dir_path = os.path.join(ROOT_DIR, CACHE_DIR, dirpath.replace("%s/" % ROOT_DIR, ""))
    try:
        cache = modification_date(os.path.join(cache_dir_path, filename))
        actual = modification_date(os.path.join(ROOT_DIR, dirpath, filename))
        return actual > cache
    except OSError:
        return True
    except:
        import traceback
        traceback.print_exc()
        return True


def exists(dirpath, filename):
    return os.path.exists(os.path.join(dirpath, filename))


def cache_file(dirpath, filename):
    cache_dir_path = os.path.join(ROOT_DIR, CACHE_DIR, dirpath.replace("%s/" % ROOT_DIR, ""))
    if not os.path.exists(cache_dir_path):
        os.makedirs(cache_dir_path)

    shutil.copy2(
        os.path.join(ROOT_DIR, dirpath, filename),
        os.path.join(cache_dir_path, filename)
    )


def publish_datetime(social_post, post):
    post_date = post["social"]["start_date"]
    post_time = social_post["time"]
    plus_days = int(social_post["publication_plus_days"])
    pub_date = datetime.datetime.strptime("%s %s" % (post_date, post_time), "%Y-%m-%d %H:%M")
    pub_date = pub_date + datetime.timedelta(days=plus_days)
    return pub_date


def publish_timestamp(social_post, post):
    dt = publish_datetime(social_post, post)
    return int(time.mktime(dt.timetuple()))


def post_in_future(social_post, post):
    now = time.mktime(datetime.datetime.now().timetuple())
    return now < publish_timestamp(social_post, post)


def publish_facebook(social_post, post):
    # print "Facebook %s" % social_post
    url = "/updates/create.json"
    # print(social_post)
    # print(post["meta"])
    # print(post["site"])

    # if post["meta"]["url"] not in social_post["content"]:
    #     text_with_url = "%s %s" % (
    #         social_post["content"],

    #     )
    # else:

    text_with_url = social_post["content"]
    data = []
    for f in facebook_profiles:
        data.append(("profile_ids[]", f["id"]))
    data.append(("text", text_with_url))
    data.append(("scheduled_at", publish_timestamp(social_post, post)))
    data.append(("media[link]", "%s/%s" % (CONFIG["url"], post["meta"]["url"])))
    data.append(("media[description]", post["meta"]["description"]))
    data.append(("media[title]", post["meta"]["title"]))
    data.append(("media[picture]", post["site"]["social_url"]))
    buffer_post(url, data)


def publish_twitter(social_post, post):
    url = "/updates/create.json"

    # if post["meta"]["url"] not in social_post["content"]:
    #     text_with_url = "%s %s" % (
    #         social_post["content"],
    #         "%s/%s" % (CONFIG["url"], post["meta"]["url"])
    #     )
    # else:
    text_with_url = social_post["content"]
    data = []
    for f in twitter_profiles:
        data.append(("profile_ids[]", f["id"]))
    data.append(("text", text_with_url))
    data.append(("scheduled_at", publish_timestamp(social_post, post)))
    data.append(("media[link]", "%s/%s" % (CONFIG["url"], post["meta"]["url"])))
    data.append(("media[description]", post["meta"]["description"]))
    data.append(("media[title]", post["meta"]["title"]))
    data.append(("media[picture]", post["site"]["social_url"]))
    data.append(("media[photo]", post["site"]["social_url"]))
    buffer_post(url, data)



def publish_instagram(social_post, post):
    url = "/updates/create.json"

    # if post["meta"]["url"] not in social_post["content"]:
    #     text_with_url = "%s %s" % (
    #         social_post["content"],
    #         "%s/%s" % (CONFIG["url"], post["meta"]["url"])
    #     )
    # else:
    text_with_url = social_post["content"]
    data = []
    for f in twitter_profiles:
        data.append(("profile_ids[]", f["id"]))
    data.append(("text", text_with_url))
    data.append(("scheduled_at", publish_timestamp(social_post, post)))
    data.append(("media[link]", "%s/%s" % (CONFIG["url"], post["meta"]["url"])))
    data.append(("media[description]", post["meta"]["description"]))
    data.append(("media[title]", post["meta"]["title"]))
    data.append(("media[picture]", post["site"]["social_url"]))
    data.append(("media[photo]", post["site"]["social_url"]))
    buffer_post(url, data)



def buffer_get(url):
    if (url[0] == "/"):
        url = url[1:]
    url = "https://api.bufferapp.com/%s" % url
    params = {
        "access_token": os.environ["BUFFER_ACCESS_TOKEN"]
    }
    r = requests.get(url, params=params)
    if not r.status_code == 200:
        error(r.json())
        raise Exception("Error connecting to buffer")
    return r.json()


def buffer_post(url, data={}):
    if (url[0] == "/"):
        url = url[1:]
    url = "https://api.bufferapp.com/1/%s" % url
    params = {
        "access_token": os.environ["BUFFER_ACCESS_TOKEN"]
    }
    r = requests.post(url, params=params, data=data)
    if not r.status_code == 200:
        error("%s" % r.json())
        raise Exception("Error connecting to buffer")
    return r.json()


def scaffold_site():
    # create folders, index, base templates, static, etc
    # create firebase.json
    # {
    #   "firebase": "inkandfeet",
    #   "public": ".build",
    #   "ignore": [
    #     "firebase.json",
    #     "**/.*",
    #     "**/node_modules/**"
    #   ]
    # }

    pass


def scaffold_piece(title, url):
    now = datetime.datetime.now()
    out_folder = os.path.join(ROOT_DIR, "posts", url)
    if not os.path.exists(out_folder):
        os.makedirs(out_folder)

    with open(os.path.join(out_folder, "meta.yml"), "wb") as f:
        f.write(u"""url: %(url)s
title: %(title)s
description: %(title)s
# post_template: letter.html
# private: true
# date: 2015-10-11
# letter_subject: The Power of Really, Really Crazy Hair
# page_name: letter
# location: Medellin, Antioquia, Colombia


published_date: %(date)s
updated_date: %(date)s

""" % {
                "url": url,
                "title": title,
                "date": "%s" % now.strftime("%Y-%m-%d %H:%M"),
                })

    with open(os.path.join(out_folder, "social.yml"), "wb") as f:
        f.write("""url: %(url)s
start_date: %(date)s
posts:
    - twitter:
        publication_plus_days: 0
        content: "First tweet"
        time: "07:00"
        image: header.jpg
    - twitter:
        publication_plus_days: 3
        content: "Second tweet body"
        time: "07:00"
        image: alt.jpg

    - facebook:
        publication_plus_days: 0
        content: "I'm posting some cool stuff."
        time: "07:00"
        image: header.jpg
    - facebook:
        publication_plus_days: 3
        content: "I found something I never expected here in mexico"
        time: "07:00"
        image: alt.jpg
""" % {
                "url": url,
                "title": title,
                "date": now.strftime("%Y-%m-%d"),
                })

    with open(os.path.join(out_folder, "piece.md"), "wb") as f:
        f.write("# %s\n\n" % title)


def build_dev_site(*args, **kwargs):
    print("args")
    print(args)
    print("kwargs")
    print(kwargs)
    return build_site(dev_mode=True)


def build_site_context(dev_mode=True, ignore_cache=True):
    print("Building context..")
    global site_info
    global private_site_info
    global pages

    try:
        settings.configure(
            TEMPLATE_DIRS=[
                os.path.join(ROOT_DIR, "templates"),
                os.path.join(INK_DIR, "templates"),
                # os.path.join(ROOT_DIR, "pages"),
            ],
            DJANGO_STATIC=not dev_mode,
            DJANGO_STATIC_USE_SYMLINK=False,
            DJANGO_STATIC_FILENAME_GENERATOR='inkblock.main.filename_generator',
            DJANGO_STATIC_COMBINE_FILENAMES_GENERATOR='inkblock.main.combine_filenames',
            DJANGO_STATIC_MEDIA_ROOTS=MEDIA_ROOTS,
            DJANGO_STATIC_NAME_PREFIX="cf/",
            DJANGO_STATIC_SAVE_PREFIX=os.path.join(BUILD_DIR, CACHE_FOREVER_DIR),
            DJANGO_STATIC_JSMIN=True,
            # INSTALLED_APPS=('sorl.thumbnail',),
            INSTALLED_APPS=('django_static',),
            STATIC_ROOT=os.path.join(BUILD_DIR,),
            MEDIA_ROOT=os.path.join(BUILD_DIR,),
            # MEDIA_ROOT=os.path.join(ROOT_DIR, "static"),
            # THUMBNAIL_DEBUG=True,
            # DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': 'Ink'}},
            STATIC_URL="/",
            # MEDIA_URL=static_url,
            # COMPRESS=True,
            # COMPRESS_URL="http://127.0.0.1:5555/",
            # ROOT_URLCONF="",
        )
        django.setup()
    except:
        pass

    site_info = {
        "pages": [],
        "posts": [],
    }
    private_site_info = {
        "pages": [],
        "posts": [],
    }
    pages = []
    now = datetime.datetime.now()
    # print os.path.join(ROOT_DIR, "pages")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "pages"), topdown=False):
        for filename in filenames:
            # print filename
            sys.stdout.write(".")
            sys.stdout.flush()
            if filename.endswith(".html") or filename.endswith(".xml"):
                if ignore_cache or is_newer(dirpath, filename):
                    with open(os.path.join(dirpath, filename)) as source:
                        context_dict = CONFIG["context"].copy()
                        if filename.endswith(".xml"):
                            page_name = filename
                            context_dict.update({
                                "dev_mode": dev,
                                "page_name": filename,
                                "url": filename,
                                "canonical_url": "%s/%s" % (static_url, page_name),
                                "updated_date": now,
                                "site_data_url": site_data_url,
                                "static_url": static_url
                            })
                            site_info["pages"].append(context_dict)
                            private_site_info["pages"].append(context_dict)
                            pages.append(filename)
                        else:
                            page_name = filename.split(".html")[0]
                            if page_name == "index":
                                page_name = ""
                            context_dict.update({
                                "dev_mode": dev,
                                "page_name": filename.split(".html")[0],
                                "url": filename.split(".html")[0],
                                "canonical_url": "%s/%s" % (static_url, page_name),
                                "updated_date": now,
                                "site_data_url": site_data_url,
                                "static_url": static_url
                            })
                            site_info["pages"].append(context_dict)
                            private_site_info["pages"].append(context_dict)
                            pages.append(filename)

    missing_meta = []
    missing_social = []
    not_published = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                # Found a folder.
                # Make sure it's got the stuffs.

                if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")):
                    # print("  ! Missing meta.yml")
                    sys.stdout.write("X")
                    sys.stdout.flush()
                    missing_meta.append(filename)
                    break
                else:
                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")) as f:
                        meta_config = load(f)
                if "published" in meta_config and meta_config["published"] is not True:
                    # print("Not published")
                    sys.stdout.write("X")
                    sys.stdout.flush()
                    not_published.append(meta_config["title"])
                else:
                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")):
                        # print("  ! Missing social.yml")
                        sys.stdout.write("X")
                        sys.stdout.flush()
                        missing_social.append(meta_config["title"])
                        break
                    else:
                        with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")) as f:
                            social_config = load(f)

                    header_image = meta_config.get("header_image", "header.jpg")

                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, filename)) as source:
                        # print(" - %s" % meta_config["title"])
                        sys.stdout.write(".")
                        sys.stdout.flush()
                        raw_source = source.read().strip()
                        first_line = raw_source.split("\n")[0]
                        if (first_line.replace("#", "").strip() == meta_config["title"]):
                            raw_source = "\n".join(raw_source.split("\n")[1:])

                        # piece_body = markdown(raw_source)
                        if "url" in meta_config:
                            url = meta_config["url"]
                        else:
                            url = dirpath.split("/")[-1]
                            if "index.html" not in filename:
                                url = url.replace(".html", "")

                        out_filename = os.path.join(BUILD_DIR, url)

                        social_image = meta_config.get("social_image", header_image)

                        resources_url = "%s/resources/%s" % (
                            static_url,
                            # meta_config["url"],
                            dirpath.replace("%s/posts/" % ROOT_DIR, "")
                        )
                        thumbs = {}

                        social_url = "%s/%s" % (resources_url, social_image)

                        context_dict = CONFIG["context"].copy()
                        context_dict.update(meta_config)
                        context_dict.update({
                            "dev_mode": dev,
                            "social_url": social_url,
                            # "social_file": social_file,
                            "thumbs": thumbs,
                            "resources_url": resources_url,
                            "published_date": date_string_to_datetime(meta_config["published_date"]),
                            "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                            # "page_name": filename.split(".html")[0],
                            "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                            "site_data_url": site_data_url,
                            "static_url": static_url,
                        })

                        pages.append(filename)

                        if "piece_context" in context_dict:
                            del context_dict["piece_context"]
                        del context_dict["site_data_url"]
                        if "social_config" in context_dict:
                            del context_dict["social_config"]
                        del context_dict["site_name"]
                        del context_dict["dev_mode"]

                # print (meta_config)
                if "private" not in meta_config or meta_config["private"] is False:
                    # print("Not private")
                    site_info["posts"].append(context_dict)

                private_site_info["posts"].append(context_dict)

    if len(missing_meta) > 0:
        print("\nMissing meta.yml for: ")
        for m in missing_meta:
            print(" - %s" % m)

    if len(missing_social) > 0:
        print("\nMissing social.yml for: ")
        for s in missing_social:
            print(" - %s" % s)
    
    if len(not_published) > 0:
        print("\nNot marked as published: ")
        for n in not_published:
            print(" - %s" % n)



def build_page(args):
    try:
        dirpath, filename, dev_mode, ignore_cache = args
        now = datetime.datetime.now()
        if ignore_cache or is_newer(dirpath, filename):
            cache_file(dirpath, filename)
            with open(os.path.join(dirpath, filename)) as source:
                t = Template(source.read())
                context_dict = CONFIG["context"].copy()
                page_name = filename.split(".html")[0]
                if page_name == "index":
                    page_name = ""
                context_dict.update({
                    "dev_mode": dev,
                    "page_name": filename.split(".html")[0],
                    "url": filename.split(".html")[0],
                    "canonical_url": "%s/%s" % (static_url, page_name),
                    "updated_date": now,
                    "site_data_url": site_data_url,
                    "site_info": site_info,
                    "private_site_info": private_site_info.copy(),
                })

                c = Context(context_dict)
                out = t.render(c).encode("utf-8")
                out_filename = os.path.join(BUILD_DIR, filename)
                if "index.html" not in filename:
                    out_filename = out_filename.replace(".html", "")
                    pass

                makedirs_threadsafe(out_filename)

                with open(out_filename, "wb") as dest:
                    dest.write(out)
                    print("Writing %s" % filename)

                append_dict = context_dict.copy()
                del context_dict["private_site_info"]
                # site_info["pages"].append(context_dict)
                private_site_info["pages"].append(append_dict)
                # pages.append(filename)
        sys.stdout.write(".")
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)


def build_pages(dev_mode=True, ignore_cache=False):
    global site_info
    print "build_pages"
    # print site_info
    build_site_context(dev_mode=dev_mode, ignore_cache=ignore_cache)
    sys.stdout.write("Building pages...")
    # p = Pool(NUM_PARALLEL_THREADS)
    files = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "pages"), topdown=False):        
        for filename in filenames:
            if filename.endswith(".html") or filename.endswith(".xml"):
                # files.append((dirpath, filename, dev_mode, ignore_cache))
                build_page((dirpath, filename, dev_mode, ignore_cache))

    # p.map(build_page, files)

    sys.stdout.write(" done. \n")

def copy_file(args):
    dirpath, filename, ignore_cache = args
    if filename not in IGNORE_FILES and (
        ignore_cache or is_newer(dirpath, filename)
    ):
        cache_file(dirpath, filename)
        out_filename = os.path.join(
            ROOT_DIR,
            BUILD_DIR,
            dirpath.replace("%s/static/" % ROOT_DIR, ""),
            filename
        )

        makedirs_threadsafe(out_filename)
        skip_image = False
        valid_operation = False
        if "images" in CONFIG and "skip" in CONFIG["images"]:
            # print filename
            if filename in CONFIG["images"]["skip"]:
                skip_image = True

        if not skip_image:
            # If we're optimizing images..
            optimization_enabled = False
            if "images" in CONFIG and "max" in CONFIG["images"]:
                optimization_enabled = True
            if not optimization_enabled:
                if "images" in CONFIG and "thumbs" in CONFIG["images"]:
                    for size in CONFIG["images"]["thumbs"]:
                        if "-thumb-%s" % size in filename:
                            optimization_enabled = True
                            break

            valid_image = False
            if optimization_enabled:
                valid_operation = generate_thumbs_and_resize(dirpath, filename, out_filename)

        if not valid_operation or skip_image:
            shutil.copyfile(
                os.path.join(dirpath, filename),
                out_filename
            )

        # print("Copying %s" % out_filename)
    sys.stdout.write(".")
    sys.stdout.flush()


def copy_static_files(ignore_cache=False):
    sys.stdout.write("Copying static files...")
    p = Pool(NUM_PARALLEL_THREADS)
    files = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "static"), topdown=False):        
        for filename in filenames:
            files.append((dirpath, filename, ignore_cache))
    
    p.map(copy_file, files)
        
    print(" done. \n")


def copy_extra_files(ignore_cache=False):
    sys.stdout.write("Copying extra files...")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "extra"), topdown=False):
        for filename in filenames:
            if filename not in IGNORE_FILES:
                if ignore_cache or is_newer(dirpath, filename):
                    cache_file(dirpath, filename)
                    # print(dirpath)
                    # print(dirpath.replace("%s/extra/" % ROOT_DIR, ""),)
                    out_filename = os.path.join(
                        ROOT_DIR,
                        BUILD_DIR,
                        # dirpath.replace("%s/extra/" % ROOT_DIR, ""),
                        filename
                    )
                    # print(out_filename)

                    makedirs_threadsafe(out_filename)

                    shutil.copyfile(
                        os.path.join(dirpath, filename),
                        out_filename
                    )
                    # print("Copying %s" % filename)
            sys.stdout.write(".")
    sys.stdout.write(" done. \n")


def compile_less(ignore_cache=False):
    print("Compile LESS")
    call(["lesscpy", os.path.join(ROOT_DIR, BUILD_DIR, "less"), "-X", "-f", "-o", os.path.join(ROOT_DIR, BUILD_DIR, "css")])


def makedirs_threadsafe(out_filename, is_dir=False):
    try:
        if out_filename:
            freaking_out = True
            while freaking_out:
                try:
                    if is_dir:
                        if not os.path.exists(out_filename):
                            os.makedirs(out_filename)
                    else:
                        if not os.path.exists(os.path.dirname(out_filename)):
                            os.makedirs(os.path.dirname(out_filename))
                    freaking_out = False
                except:
                    import traceback; traceback.print_exc();
                    time.sleep(random.random())
                    pass
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)

def build_post(args):
    try:
        dirpath, filename, dev_mode, ignore_cache = args
        # Found a folder.
        # Make sure it's got the stuffs.
        if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")):
            print("  ! Missing meta.yml")
            return
        else:
            with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")) as f:
                meta_config = load(f)
        if "published" in meta_config and meta_config["published"] is not True:
            print("Not published")
        else:
            if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")):
                print("  ! Missing social.yml")
                return
            else:
                with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")) as f:
                    social_config = load(f)

            header_image = meta_config.get("header_image", "header.jpg")
            no_header = False
            if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, header_image)):
                print("  ! Missing header.jpg")
                no_header = True

            with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, filename)) as source:
                print(" - %s" % meta_config["title"])
                raw_source = source.read().strip()
                first_line = raw_source.split("\n")[0]
                if (first_line.replace("#", "").strip() == meta_config["title"]):
                    raw_source = "\n".join(raw_source.split("\n")[1:])

                # piece_body = markdown(raw_source)
                if "url" in meta_config:
                    url = meta_config["url"]
                else:
                    url = dirpath.split("/")[-1]
                    if "index.html" not in filename:
                        url = url.replace(".html", "")

                out_filename = os.path.join(BUILD_DIR, url)

                social_image = meta_config.get("social_image", header_image)

                resources_url = "%s/resources/%s" % (
                    static_url,
                    # meta_config["url"],
                    dirpath.replace("%s/posts/" % ROOT_DIR, "")
                )
                thumbs = {}
                if no_header:
                    social_file = None
                    social_url = ""
                else:
                    social_file = open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image))
                    social_url = "%s/%s" % (
                        resources_url,
                        social_image,
                    )
                    renamed_out = social_url.split(".")
                    renamed_out[-2] = "%s-%%s" % renamed_out[-2]
                    renamed_out = ".".join(renamed_out)

                    # make thumbs
                    if "width" in CONFIG["images"]["thumbs"]:
                        for width in CONFIG["images"]["thumbs"]["width"]:
                            thumb_out = renamed_out % ("%sw" % width)
                            # print(thumb_out)
                            thumbs["%sw" % width] = thumb_out.replace(resources_url, "")

                    if "height" in CONFIG["images"]["thumbs"]:
                        for height in CONFIG["images"]["thumbs"]["height"]:
                            thumb_out = renamed_out % ("%sh" % height)
                            # print(thumb_out)
                            thumbs["%sh" % height] = thumb_out.replace(resources_url, "")

                context_dict = CONFIG["context"].copy()
                context_dict.update(meta_config)
                context_dict.update({
                    "dev_mode": dev,
                    "social_url": social_url,
                    "social_file": social_file,
                    "thumbs": thumbs,
                    "resources_url": resources_url,
                    "published_date": date_string_to_datetime(meta_config["published_date"]),
                    "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                    # "page_name": filename.split(".html")[0],
                    "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                    "site_data_url": site_data_url,
                    "site_info": site_info,
                })
                if ignore_cache or is_newer(dirpath, filename) or is_newer(dirpath, "meta.yml"):
                    cache_file(dirpath, filename)
                    cache_file(dirpath, "meta.yml")
                    c = Context(context_dict)
                    raw_source = raw_source.replace(
                        '{%% thumbnail "',
                        '{%% thumbnail "posts/%s/' % meta_config["url"],
                    )
                    raw_source = raw_source.replace(
                        "{%% thumbnail '",
                        "{%% thumbnail 'posts/%s/" % meta_config["url"],
                    )
                    t = Template(raw_source)
                    parsed_source = t.render(c)

                    piece_body = markdown(parsed_source)
                    piece_body = piece_body.replace(u"’", '&rsquo;').replace(u"“", '&ldquo;').replace(u"”", '&rdquo;').replace(u"’", "&rsquo;");

                    context_dict.update({
                        "piece_html": piece_body,
                    })
                    c = Context(context_dict)

                    t = Template("""{% extends '""" + context_dict["post_template"] + """' %}""")
                    out = t.render(c).encode("utf-8")

                    makedirs_threadsafe(out_filename)
                    
                    # out_folder = os.path.join(ROOT_DIR, BUILD_DIR, "resources", meta_config["url"])
                    out_folder = os.path.join(ROOT_DIR, BUILD_DIR, "resources", dirpath.replace("%s/posts/" % ROOT_DIR, ""))
                    # print(out_folder)
                    makedirs_threadsafe(out_folder, is_dir=True)

                    social_outfilename = os.path.join(out_folder, social_image)
                    valid_operation = generate_thumbs_and_resize(
                        dirpath,
                        social_image,
                        social_outfilename
                    )

                    if not valid_operation and not no_header:
                        shutil.copyfile(
                            os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image),
                            social_outfilename
                        )

                    with open(out_filename, "wb") as dest:
                        dest.write(out)
                        # print("Writing %s" % filename)

                    # Bundle this in to a base template, as a popup?
                    # if dev:
                    #     out_filename = "%s-social" % out_filename
                    #     t = Template("""{% extends "social.html" %}""")
                    #     piece_context = context_dict.copy()
                    #     context_dict = CONFIG["context"].copy()
                    #     context_dict.update(meta_config)
                    #     context_dict.update({
                    #         "dev_mode": dev,
                    #         "social_config": social_config,
                    #         "piece_context": piece_context,
                    #         "piece_html": piece_body,
                    #         "social_url": social_url,
                    #         "thumbs": thumbs,
                    #         "social_file": social_file,
                    #         "resources_url": resources_url,
                    #         "published_date": date_string_to_datetime(meta_config["published_date"]),
                    #         "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                    #         # "page_name": filename.split(".html")[0],
                    #         "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                    #         "site_data_url": site_data_url,
                    #     })
                    #     c = Context(context_dict)
                    #     out = t.render(c).encode("utf-8")

                    #     if not os.path.exists(os.path.dirname(out_filename)):
                    #         os.makedirs(os.path.dirname(out_filename))

                    #     with open(out_filename, "wb") as dest:
                    #         dest.write(out)
                    #         print("Writing %s-social" % filename)

                    # pages.append(filename)

                    # del context_dict["piece_html"]
                    # del context_dict["social_file"]
                    # if "piece_context" in context_dict:
                    #     del context_dict["piece_context"]
                    # del context_dict["site_data_url"]
                    # if "social_config" in context_dict:
                    #     del context_dict["social_config"]
                    # del context_dict["site_name"]
                    # del context_dict["dev_mode"]

                if social_file:
                    social_file.close()

        # print (meta_config)
        # if "private" not in meta_config or meta_config["private"] is False:
        #     # print("Not private")
        #     site_info["posts"].append(context_dict)

        # private_site_info["posts"].append(context_dict)
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)

def build_posts(dev_mode=True, ignore_cache=False):
    build_site_context(dev_mode=dev_mode, ignore_cache=ignore_cache)
    # Build posts
    sys.stdout.write("Building posts...\n")
    p = Pool(NUM_PARALLEL_THREADS)
    files = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):        
        for filename in filenames:
            if "piece.md" in filename:
                files.append((dirpath, filename, dev_mode, ignore_cache))

    p.map(build_post, files)


def optimize_images(ignore_cache=False):
    print("Optimizing images...")
    print(os.path.join(ROOT_DIR, BUILD_DIR))
    call("cd %s;picopt -rG -j %s *" % (os.path.join(ROOT_DIR, BUILD_DIR), NUM_PARALLEL_THREADS), shell=True)


def create_sitemap_xml(ignore_cache=False):
    # create sitemaps
    print("Sitemap.xml")
    with open(os.path.join(ROOT_DIR, BUILD_DIR, "sitemap.xml"), "wb") as sitemap:
        context_dict = {
            "info": private_site_info,
        }
        c = Context(context_dict)
        t = Template("""{% extends "sitemap.xml" %}""")
        out = t.render(c)
        sitemap.write(out.encode('utf-8'))


def create_site_jsons(ignore_cache=False):
    site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "site.json")
    private_site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "private.json")

    makedirs_threadsafe(site_json_filename)

    print("site.jsons")
    with open(site_json_filename, "wb") as site_json:
        out = u"%s" % json.dumps(site_info, cls=DateTimeEncoder, sort_keys=True)
        site_json.write(out.encode('utf-8'))

    with open(private_site_json_filename, "wb") as private_site_json:
        out = u"%s" % json.dumps(private_site_info, cls=DateTimeEncoder, sort_keys=True)
        private_site_json.write(out.encode('utf-8'))


def build_static_files():
    copy_static_files()
    copy_extra_files()
    compile_less()


def build_template_stuff():
    build_static_files()
    build_pages(ignore_cache=True)
    build_posts(ignore_cache=True)


def crunch_page(page):
    return
    try:
        if page["url"] == "index":
            page["url"] = "index.html"
        print(" - %s" % page["url"])
        # cmd = "cd .build; cp '%(url)s' '%(url)s.html'; critical %(url)s.html -i -m -w 1600,1200,320,400,600,800 -ii 4096 > %(url)s; rm %(url)s.html; html-minifier %(url)s --remove-comments --remove-optional-tags --sort-class-name --sort-attributes --collapse-whitespace --conservative-collapse -o '%(url)s.html'; mv '%(url)s.html' '%(url)s'  &> /dev/null" % page
        cmd = "cd .build; cp '%(url)s' '%(url)s.html'; critical %(url)s.html -i -m -w 1600,1200,320,400,600,800 -h 1600 -ii 4096 > %(url)s; rm %(url)s.html; html-minifier %(url)s --remove-comments  --sort-class-name --sort-attributes  -o '%(url)s.html'; mv '%(url)s.html' '%(url)s'  &> /dev/null" % page
        call(cmd, shell=True)
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)


def optimize_html(ignore_cache=False):
    # print(private_site_info)
    try:
        call("critical --help &> /dev/null", shell=True)
        call("html-minifier -h &> /dev/null", shell=True)
        print("Optimizing and inlining CSS...")
        p = Pool(NUM_PARALLEL_THREADS)
        p.map(crunch_page, private_site_info["pages"])
        p.map(crunch_page, private_site_info["posts"])

    except OSError:
        print ("Skipping optimization. Run `npm install -g critical html-minifier` to use inline optimization.")
        pass


def build_site(dev_mode=False, clean=False, ignore_cache=None):
    try:
        global pages
        global site_info
        global private_site_info
        global dev
        global static_url
        global site_data_url
        dev = dev_mode
        pages = []
        site_info = {}
        private_site_info = {}

        if clean and os.path.exists(BUILD_DIR):
            shutil.rmtree(BUILD_DIR)
        makedirs_threadsafe(BUILD_DIR, is_dir=True)

        if dev:
            static_url = "http://localhost:%s" % DEV_PORT
        else:
            static_url = CONFIG["url"]

        site_data_url = "/static/site.json"

        site_info["static_url"] = static_url
        # site_info["pages"] = []
        # site_info["posts"] = []
        private_site_info["static_url"] = static_url
        # private_site_info["pages"] = []
        # private_site_info["posts"] = []

        if ignore_cache is None:
            ignore_cache = not dev_mode

        copy_static_files(ignore_cache=ignore_cache)
        copy_extra_files(ignore_cache=ignore_cache)
        compile_less(ignore_cache=ignore_cache)
        build_pages(dev_mode=dev_mode, ignore_cache=ignore_cache)
        build_posts(dev_mode=dev_mode, ignore_cache=ignore_cache)
        if not dev:
            optimize_images(ignore_cache=ignore_cache)
            optimize_html(ignore_cache=ignore_cache)
        create_sitemap_xml(ignore_cache=ignore_cache)
        create_site_jsons(ignore_cache=ignore_cache)

        print("Site built.")
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)


def serve_site():
    server = Server()
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'pages'), build_pages)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'pages'), build_pages)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'posts'), build_posts)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'static'), build_static_files)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'templates'), build_template_stuff)
    server.watch('%s/*' % os.path.join(INK_DIR, 'templates'), build_template_stuff)
    server.serve(root='.build/', host="0.0.0.0", open_url_delay=0.5, port=DEV_PORT)


@click.group()
def cli():
    """Ink.  Publication made simple."""
    pass


@cli.command()
def build():
    build_site(dev_mode=False)


def do_purge():
    if "CLOUDFLARE_API_KEY" not in os.environ:
        raise Exception("Missing CLOUDFLARE_API_KEY.")
    if "CLOUDFLARE_EMAIL" not in os.environ:
        raise Exception("Missing CLOUDFLARE_EMAIL.")

    api_key = os.environ["CLOUDFLARE_API_KEY"]
    email = os.environ["CLOUDFLARE_EMAIL"]

    # Get the zone from cloudflare
    headers = {
        "X-Auth-Key": api_key,
        "X-Auth-Email": email,
        "Content-Type": "application/json",
    }
    url = "https://api.cloudflare.com/client/v4/zones/"
    params = {
        "name": CONFIG["url"].replace("https://", "").replace("http://", ""),
        "status": "active",
        "page": 1,
        "per_page": 20,
        "order": "status",
        "direction": "desc",
        "match": "all",
    }

    r = requests.get(url, params=params, headers=headers)

    if not r.status_code == 200:
        print("Error at Cloudflare:")
        print(r.json())
        raise Exception("Cache not purged.")

    if "result" in r.json() and len(r.json()["result"]) == 1:
        zone_id = r.json()["result"][0]["id"]
        url = "%s%s/purge_cache" % (url, zone_id)

        data = {
            "purge_everything": True
        }

        r = requests.delete(url, data=json.dumps(data), headers=headers)

        if not r.status_code == 200:
            print(r.status_code)
            print(r.json())
            raise Exception("Error purging cache: %s" % r.json()["errors"][0]["message"])
    else:
        print("Either there isn't a record at cloudflare with domain %s, or there are several." % CONFIG["url"])
        raise Exception("Cache not purged.")
    print("Cache purged.")


@cli.command()
def purge():
    do_purge()


@cli.command()
def write():
    """Start a new piece"""
    click.echo("Fantastic. Let's get started. ")
    title = click.prompt("What's the title?")

    # Make sure that title doesn't exist.
    url = slugify(title)
    url = click.prompt("What's the URL?", default=url)

    # Make sure that title doesn't exist.
    click.echo("Got it. Creating %s..." % url)
    scaffold_piece(title, url)


@cli.command()
def scaffold():
    """Start a new site."""
    click.echo("A whole new site? Awesome.")
    title = click.prompt("What's the title?")
    url = click.prompt("Great. What's url? http://")

    # Make sure that title doesn't exist.
    click.echo("Got it. Creating %s..." % url)
    # call(["firebase" "init"])


@cli.command()
def publish():
    """Publish the site"""
    try:
        build_site(dev_mode=False, clean=True)
        click.echo('Deploying the site...')
        # call("firebase deploy", shell=True)
        call("rsync -avz -e ssh --progress %s/ %s" % (BUILD_DIR, CONFIG["scp_target"],), shell=True)
        if "cloudflare" in CONFIG and "purge" in CONFIG["cloudflare"] and CONFIG["cloudflare"]["purge"]:
            do_purge()
    except (KeyboardInterrupt, SystemExit):
        raise
        sys.exit(1)


@cli.command()
def promote():
    """Schedule all the social media posts."""

    if "BUFFER_ACCESS_TOKEN" not in os.environ:
        warn("Missing BUFFER_ACCESS_TOKEN.")
        echo("To publish to social medial, you'll need an access token for buffer.")
        echo("The simplest way to get one is to create a new app here: https://buffer.com/developers/apps")
        echo("The token you want is the 'Access Token'")
        echo("Once you have it, make it available to ink by putting it in the environment.")

    # GET https://api.bufferapp.com/1/profiles.json
    echo("Verifying available profiles on buffer")
    profiles = buffer_get("/1/profiles.json")
    for p in profiles:
        supported_profile = False
        if p["formatted_service"].lower() == "facebook" or p["formatted_service"].lower() == "facebook page":
            facebook_profiles.append(p)
            supported_profile = True
        elif p["formatted_service"].lower() == "twitter":
            twitter_profiles.append(p)
            supported_profile = True

        if supported_profile:
            click.secho(u"✓  %s: %s" % (p["formatted_service"], p["formatted_username"]), fg="green")

    echo("Checking publication status...")
    site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "private.json")
    with open(site_json_filename, "r") as site_json:
        site = load(site_json)

    echo('Reviewing social posts...')

    posts = {}
    unpublished_posts = []

    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                if exists(dirpath, "social.yml") and exists(dirpath, "meta.yml"):
                    with open(os.path.join(dirpath, "social.yml")) as f:
                        social = load(f)

                    with open(os.path.join(dirpath, "meta.yml")) as f:
                        meta = load(f)

                    if "url" in meta:
                        site_json_entry = None
                        for sp in site["posts"]:
                            if meta["url"] == sp["url"]:
                                site_json_entry = sp
                                break

                        posts[meta["url"]] = {
                            "meta": meta,
                            "social": social,
                            "dirpath": dirpath,
                            "site": site_json_entry,
                        }
                        if "published" not in social or social["published"] is not True:
                            unpublished_posts.append(meta["url"])
                    else:
                        warn("No url found for %s" % dirpath.replace(ROOT_DIR))

    automark_set = False
    automark = None
    for u in unpublished_posts:
        post = posts[u]

        if "posts" in post["social"] and post["social"]["posts"] and len(post["social"]["posts"]) > 0:
            facebook_posts = []
            twitter_posts = []
            mark_as_published = False

            has_valid_post = False
            for p in post["social"]["posts"]:
                try:
                    if len(p.keys()) != 1:
                        error("Something's formatted wrong in %s's social.yml" % u)
                        break
                    if p.keys()[0] == "facebook":
                        facebook_posts.append(p["facebook"])
                        if post_in_future(p["facebook"], post):
                            has_valid_post = True
                    elif p.keys()[0] == "twitter":
                        if post_in_future(p["twitter"], post):
                            has_valid_post = True
                        twitter_posts.append(p["twitter"])
                    else:
                        warn("Unknown post type: %s.  Skipping." % p.keys()[0])
                except:
                    error("Error parsing social.yml for \"%s\"" % post["meta"]["title"])
                    import traceback
                    traceback.print_exc()

            if not has_valid_post:
                if automark:
                    mark_as_published = True
                else:
                    warn('"%s" hasn\'t been published, but all posts are in the past.' % post["meta"]["title"])
                    if click.confirm("Mark as published?"):
                        mark_as_published = True
                        if not automark_set:
                            if click.confirm("Mark all other similar posts as published?"):
                                automark = True
                            automark_set = True
            else:
                echo('\n"%s" hasn\'t been published to social media.' % post["meta"]["title"])
                if len(facebook_posts) > 0:
                    echo("  Facebook:")
                    for p in facebook_posts:
                        if (len(p["content"]) > 40):
                            truncated_content = "%s..." % p["content"][:40]
                        else:
                            truncated_content = p["content"]
                        if post_in_future(p, post):
                            echo("   - %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                        else:
                            warn("   - %s:  \"%s\" skipping (past)" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                echo("  Twitter:")
                if len(twitter_posts) > 0:
                    for p in twitter_posts:
                        if (len(p["content"]) > 40):
                            truncated_content = "%s..." % p["content"][:40]
                        else:
                            truncated_content = p["content"]
                        if post_in_future(p, post):
                            echo("   - %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                        else:
                            warn("   - %s:  \"%s\" skipping (past)" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))

                if click.confirm(click.style("  Publish now?", fg="green")):
                    mark_as_published = True
                    echo("  Publishing...")
                    for p in facebook_posts:
                        if post_in_future(p, post):
                            publish_facebook(p, post)
                            if (len(p["content"]) > 40):
                                truncated_content = "%s..." % p["content"][:40]
                            else:
                                truncated_content = p["content"]
                            click.secho(u"   ✓ Facebook %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ), fg="green")
                    for p in twitter_posts:
                        if post_in_future(p, post):
                            publish_twitter(p, post)
                            if (len(p["content"]) > 40):
                                truncated_content = "%s..." % p["content"][:40]
                            else:
                                truncated_content = p["content"]
                            click.secho(u"   ✓ Twitter %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ), fg="green")

                    echo("  Published.")

            # Save as published.
            if mark_as_published or automark:
                post["social"]["published"] = True
                with open(os.path.join(post["dirpath"], "social.yml"), "w") as f:
                    dump(post["social"], f, default_flow_style=False, width=1000)

    if click.confirm("Publish your entire backlog to buffer?"):
        print ("dope")


@cli.command()
def list():
    """List all posts"""
    click.echo('List all posts')


@cli.command()
def serve():
    """Serve the site for local testing and editing."""
    build_site(dev_mode=True)
    serve_site()

if __name__ == '__main__':
    cli()
