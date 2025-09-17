REPOROOT=../../..
# Use make help, to see the available rules
include $(REPOROOT)/transforms/.make.cicd.targets

#
# This is intended to be included across the Makefiles provided within
# a given transform's directory tree,  so must use compatible syntax.
#
################################################################################
# This defines the name of the transform and is used to match against
# expected files and is used to define the transform's image name. 
TRANSFORM_NAME=$(shell basename `pwd`)

################################################################################



run-cli-sample:
	make venv
	source venv/bin/activate && \
	$(PYTHON) -m dpk_$(TRANSFORM_NAME).transform_python \
                --data_local_config "{ 'input_folder' : 'test-data/input', 'output_folder' : 'output'}"  \
                --gcls_model_credential "PUT YOUR OWN HUGGINGFACE CREDENTIAL"	\
				--gcls_model_file_name "['fasttext_medical.bin']"	\
				--gcls_model_url "['ibm-granite/GneissWeb.Med_classifier']"\
				--gcls_output_label_column_name "['label']"	\
				--gcls_content_column_name "text"

run-cli-ray-sample: 
	make venv
	source venv/bin/activate && \
	$(PYTHON) -m dpk_$(TRANSFORM_NAME).ray.transform \
                --run_locally True --data_local_config "{ 'input_folder' : 'test-data/input', 'output_folder' : 'output'}"  \
                --gcls_model_credential "PUT YOUR OWN HUGGINGFACE CREDENTIAL"	\
				--gcls_model_file_name "['fasttext_medical.bin']"	\
				--gcls_model_url "['ibm-granite/GneissWeb.Med_classifier']"\
				--gcls_output_label_column_name "['label']"	\
				--gcls_content_column_name "text"


run-docker-ray-sample: 
	# make image-ray
	docker run -it --rm --env-file .env gneissweb_classification-ray:latest \
	$(PYTHON) -m dpk_$(TRANSFORM_NAME).ray.transform \
                --run_locally True --data_s3_config "{'input_folder': 'bucket-wikimedia-1/ededup', 'output_folder': 'bucket-wikimedia-1/gneissmath'}"  \
				--gcls_model_file_name "['math.bin']"	\
				--gcls_model_url "['s3://bucket-wikimedia-1/math.bin']"\
				--gcls_output_label_column_name "['math_label']"	\
				--gcls_output_score_column_name "['math_score']"	\
				--gcls_content_column_name "contents" \
				--data_max_files 1 \
				--runtime_num_workers 5 --runtime_worker_options "{ 'num_cpus': 0.8, 'max_restarts': 0, 'max_task_retries': 0 }"
    

run-ray-sample: 
	make venv
	source venv/bin/activate && \
	$(PYTHON) -m dpk_$(TRANSFORM_NAME).ray.transform \
                --run_locally True --data_s3_config "{'input_folder': 'bucket-wikimedia-1/ededup', 'output_folder': 'bucket-wikimedia-1/gneissmath'}"  \
				--gcls_model_file_name "['math.bin']"	\
				--gcls_model_url "['s3://bucket-wikimedia-1/math.bin']"\
				--gcls_output_label_column_name "['math_label']"	\
				--gcls_output_score_column_name "['math_score']"	\
				--gcls_content_column_name "contents" \
				--data_max_files -1 \
				--runtime_num_workers 1 --runtime_worker_options "{ 'num_cpus': 0.8, 'max_restarts': 0, 'max_task_retries': 0 }"