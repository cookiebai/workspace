build:
	cd ./daemon && go build
	-mkdir scripts
	mv ./daemon/satellite ./scripts/entrypoint
	sudo docker build --no-cache . -t realssd/satellite-router
build-file: build
	sudo docker save realssd/satellite-router -o satellite-router-node.tar.gz
clean:
	rm ./scripts/entrypoint
