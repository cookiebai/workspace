build:
	sudo docker build . -t build-base
build-file: build
	sudo docker save build-base -o node-image-base.tar.gz