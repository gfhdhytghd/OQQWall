#!/bin/bash
input="$1"
mkdir ./getmsgserv/post-step5/${input}
rm ./getmsgserv/post-step5/${input}/*
magick convert -density 320 -quality 95 ./getmsgserv/post-step4/${input}.pdf ./getmsgserv/post-step5/${input}/${input}.jpeg
