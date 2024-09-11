# Setup a Local Python SOURCE Dev Environment

This is for developing with src version.  **Recommended for DPK developers**

## Step-1: Install Anaconda Python environment

(You can skip this step if you have already have python 3.10 or 3.11)

You can install Anaconda by following the [guide here](https://www.anaconda.com/download/).

We will create an environment for this workshop with all the required libraries installed.

## Step-2: Setup a conda env

(You can skip this step if you have python 3.10 or 3.11 already installed)

```bash
conda create -n data-prep-kit-1-src-dev -y python=3.11

# activate the new conda environment
conda activate data-prep-kit-1-src-dev
# make sure env is swithced to data-prep-kit-1-dev

## Check python version
python --version
# should say : 3.11
```

## Step-3: Install System Dependencies

If you are using a linux system, install gcc using the below commands:

```bash
conda install gcc_linux-64
conda install gxx_linux-64
```


## Step-4: Create a venv

Two options

### 4A - Using Make (Recommended)

```bash
cd examples/notebooks/rag

make clean  venv
```

### 4B - Manually

```bash
cd examples/notebooks/rag

python -m venv venv

## activate venv
source ./venv/bin/activate


## Install requirements
bash ./prepare_env.sh
```

If any issues see [troubleshooting tips](#troubleshooting-tips)


## Step-5: Launch Jupyter

`./venv/bin/jupyter lab`

This will usually open a browser window/tab.  We will use this to run the notebooks

**Note:**: Make sure to run `./venv/bin/jupyter lab`, so it can load installed dependencies correctly.

## Troubleshooting Tips

### fasttext compile issue with GCC/G++ compiler version 13

`pip install` may fail because one of the python dependencies, `fasttext==0.9.2` compiles with GCC/G++ version 11, not version 13.

Here is how to fix this error:

```bash
## These instructions are for Ubuntu 22.04 and later

sudo apt update

## install GCC/G++ compilers version 11 
sudo apt install -y gcc-11  g++-11

## Verify installation
gcc-11  --version
g++-11  --version
# should say 11

## Set the compiler before doing pip install
CC=gcc-11  pip install -r requirements.txt 
```