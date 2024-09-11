#!/bin/bash

# Set REPOROOT
REPO_ROOT=$(cd ../../../ && pwd && cd - > /dev/null )
echo $REPO_ROOT

# pip install notebook ipywidgets


packages=(
"$REPO_ROOT/transforms/language/pdf2parquet/python"
"$REPO_ROOT/transforms/language/pdf2parquet/ray"
"$REPO_ROOT/transforms/language/lang_id/python"
"$REPO_ROOT/transforms/language/lang_id/ray"
"$REPO_ROOT/transforms/language/doc_quality/python"
"$REPO_ROOT/transforms/language/doc_quality/ray"
"$REPO_ROOT/transforms/language/doc_chunk/python"
"$REPO_ROOT/transforms/language/doc_chunk/ray"
"$REPO_ROOT/transforms/language/text_encoder/python"
"$REPO_ROOT/transforms/language/text_encoder/ray"
"$REPO_ROOT/transforms/universal/ededup/python"
"$REPO_ROOT/transforms/universal/ededup/ray"
"$REPO_ROOT/transforms/universal/fdedup/ray"
"$REPO_ROOT/transforms/universal/filter/python"
"$REPO_ROOT/transforms/universal/filter/ray"
"$REPO_ROOT/transforms/universal/doc_id/ray"
)

# Iterate through the list and install requirements from each file
for pkg in "${packages[@]}"
do
  echo "Install package $pkg"
  pip install -e "$pkg"
done

## install other depdendencies
pip install \
  pymilvus \
  pymilvus[model] \
  datasets \
  torch \
  sentence-transformers \
  pandas \
  pyarrow \
  replicate \
  llama-index \
  llama-index-embeddings-huggingface \
  llama-index-llms-replicate \
  llama-index-vector-stores-milvus \
  python-dotenv==1.0.0 \
  humanfriendly \
  jupyterlab \
  ipykernel \
  ipython \
  ipywidgets \
  IProgress \
  chardet==5.2.0 \
  charset-normalizer==3.3.2 