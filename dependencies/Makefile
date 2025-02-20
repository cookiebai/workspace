build:
	cd custom-etcd && make build-file
	sudo mv custom-etcd/opensn_etcd.tar.gz ./
	cd custom-influxdb && make build-file
	sudo mv custom-influxdb/opensn_influxdb.tar.gz ./
	cd custom-codeserver && make build-file
	sudo mv custom-codeserver/opensn_codeserver.tar.gz ./
	
clean:
	sudo rm *.tar.gz