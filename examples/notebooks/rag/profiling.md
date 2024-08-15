# Profiling Code

PDF2Parquet step seems very slow.

it is processing at the rate of 1 page / sec.  So for 3 documents with 300 pages total, it is taking 300 seconds = 5 minutes!

Here is how I am profiling it

First simple code with pdf2parquet transform : [test_pdf2pq_py.py](test_pdf2pq_py.py)

Run it under profiler

`py-spy record -o test_pdf2pq_py.svg -- python test_pdf2pq_py.py`

Open SVG file in Chrome browser:   [test_pdf2pq_py.svg](test_pdf2pq_py.svg)

