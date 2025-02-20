build:
	cp -r ../../TopoConfigurators ./TopoConfigurator
	sudo docker build . -t realssd/opensn_codeserver:latest
	rm -rf ./TopoConfigurators

build-file: build
	sudo docker save realssd/opensn_codeserver -o opensn_codeserver.tar.gz