build:
	cd ./daemon && go build
	-mkdir scripts
	mv ./daemon/ground ./scripts/entrypoint
	sudo docker build --no-cache . -t realssd/ground-station
build-file: build
	sudo docker save realssd/ground-station -o ground-station-node.tar.gz
clean:
	rm ./scripts/entrypoint
