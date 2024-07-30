#!/bin/bash

# 定义输入和输出文件
input="$1"
google-chrome-stable --headless --print-to-pdf=$(pwd)/getmsgserv/post-step4/${input}.pdf --no-header --run-all-compositor-stages-before-draw \
--no-pdf-header-footer \
--pdf-page-orientation=portrait \
--no-margins \
--enable-background-graphics \
--print-background=true \
file://$(pwd)/getmsgserv/post-step3/${input}.html
