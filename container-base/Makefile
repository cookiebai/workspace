build:
	cd build-base && make build-file
	sudo mv build-base/node-image-base.tar.gz ./
	cd ground-station && make build-file
	sudo mv ground-station/ground-station-node.tar.gz ./
	cd satellite-router && make build-file
	sudo mv satellite-router/satellite-router-node.tar.gz ./
clean:
	sudo rm -rf *.tar.gz