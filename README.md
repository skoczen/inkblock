Ink is a simpler way to create and publish writing on the web.



It's true, there are a million static site generators out there.  The best five or six are better at their jobs than Ink is, to be honest.  But not one of them is slightly involved in the most important part of publishing online - *getting it in front of human beings*.

Ink handles your pages, blog posts, and scheduled social posts and just makes everything work. Simply.

# Installation

1. `pip install ink`
2. `npm install -g firebase-tools`  Optional, to use the [firebase deploy]()
3. `pip install picopt; brew install optipng jpeg gifsicle mozjpeg; ln -s /usr/local/Cellar/mozjpeg/2.1/bin/jpegtran /usr/local/bin/mozjpeg` Optional, to use image optimization (Mac OS X shown.)


Me: npm install -g blaze_compiler


# Usage


```bash
$ ink new piece
Title: The Mexican Secret of Happiness
URL: the-mexican-secret-of-happiness [Y/n]

> Piece #24 created.  Opening editor.

$ 

# Editing happens

$ ink publish

Publishing Ink and Feet.
Pages:
  - /home... published
  - /letter... published
Posts:
  - /the-mexican-secret-to-happiness... published
```


This is the first install of an Ink site.


# Footprints: A complimentary server

http://click.pocoo.org/5/


Specs:
ink serve
ink build
ink new
ink publish
# ink list
# ink help
# ink (alias for ink help)


pages are built with: 
    name stripped of html, or "url" override.
    put up as text/html, no extension, pretty URLs.




User data

/users/:uid
    /profile
    /piece_url
        /hearted: true
        /read: true

/events
    { 
        uid
        timestamp
        url
        action
        type
    }