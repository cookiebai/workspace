build:
	cd custom-etcd && make build-file
	sudo mv custom-etcd/opensn_etcd.tar.gz ./
	cd custom-influxdb && make build-file
	sudo mv custom-influxdb/opensn_influxdb.tar.gz ./
	cd custom-redis && make build-file
	sudo mv custom-redis/opensn_redis.tar.gz ./
	
clean:
	sudo rm *.tar.gz