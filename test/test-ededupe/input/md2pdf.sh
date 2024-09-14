#!/bin/bash

for f in *.md
do 
    pandoc  -o "$(basename $f '.md').pdf"  $f
done