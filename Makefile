build:
	-mkdir opensn_build
	cd ui && make build
	mkdir -p daemon/share/static/dist/
	cp -r ui/build/ daemon/share/static/dist/
	cd container-base && make build
	cd dependencies && make build
	cd daemon && make build
	mkdir -p opensn_build/node-images
	sudo cp container-base/*.tar.gz opensn_build/node-images/
	sudo cp -r daemon/opensn-daemon opensn_build/
	mkdir -p opensn_build/depend-images
	sudo cp dependencies/*.tar.gz opensn_build/depend-images/
	sudo cp -r TopoConfigurators opensn_build/
	sudo cp -r tools opensn_build/
	sudo tar cvf opensn_build.tar.gz opensn_build/*
example_images:
	echo "not implement"
example_config:
	echo "not implement"
clean:
	-sudo rm -rf opensn_build
	-sudo rm opensn_build.tar.gz
	cd ui && make clean
	cd container-base && make clean
	cd dependencies && make clean
	cd daemon && make clean