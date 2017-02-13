Inkblock is a simpler way to create and publish writing on the web.


It's true, there are a million static site generators out there.  The best five or six are better at their jobs than Inkblock is, to be honest.  But not one of them is slightly involved in the most important part of publishing online - *getting it in front of human beings*.

Inkblock handles your pages, blog posts, and scheduled social posts and just makes everything work. Simply.

**Notes:** I'm using this in production, but it's still fairly tuned to my needs, and needs some abstraction.  If you need something bulletproof today, use Cactus.


# Installation

1. `pip install inkblock`
3. `npm install -g critical html-minifier` Optional, will optimize html, inline CSS and such for fastest loads.
3. `pip install picopt; brew install optipng jpeg gifsicle mozjpeg; ln -s /usr/local/Cellar/mozjpeg/2.1/bin/jpegtran /usr/local/bin/mozjpeg` Optional, to use image optimization (Mac OS X shown.)



# What it does

Builds a static site using django templates, smart css/js compression and combining, and uploads that site to firebase or any rsync-capable host.

Integrates with cloudflare for caching, and buffer for social media scheduling.

Your workflow is as follows:

```bash
ink write # write the thing
ink serve # test, look
ink publish # put it online
ink promote # put it on the social medias.
```


# Usage


```bash
$ Usage: ink [OPTIONS] COMMAND [ARGS]...

  Ink.  Publication made simple.

Options:
  --help  Show this message and exit.

Commands:
  build
  list      List all posts
  promote   Schedule all the social media posts.
  publish   Publish the site
  purge
  scaffold  Start a new site.
  serve     Serve the site for local testing and editing.
  write     Start a new piece

```

