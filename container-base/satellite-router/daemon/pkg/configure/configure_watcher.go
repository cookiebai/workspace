package configure

import (
	"encoding/json"
	"os"
	"satellite/data"
	"satellite/model"
	"time"

	"github.com/sirupsen/logrus"
)

var NewConfigurationChan chan model.TopoInfo = make(chan model.TopoInfo)

func parseConfigFile(path string) (model.TopoInfo, error) {
	var ret model.TopoInfo
	fd, err := os.Open(path)
	if err != nil {
		logrus.Errorf("Open Topo Infomation File Error: %s", err.Error())
		return ret, err
	}
	defer fd.Close()
	decoder := json.NewDecoder(fd)
	err = decoder.Decode(&ret)
	if err != nil {
		logrus.Errorf("Decode Json Topo Infomation Error: %s", err.Error())
		return ret, err
	}
	return ret, nil
}

func InitConfigurationWatcher(watchPath string) {
	go func() {
		// One fsnotify instance per container exhausts the host-wide inotify
		// instance limit at a few hundred emulated nodes. Configuration changes
		// are infrequent, so portable polling is cheaper and scales linearly.
		var lastMod time.Time
		for {
			info, err := os.Stat(watchPath)
			if err == nil && info.ModTime().After(lastMod) {
				newConfiguration, parseErr := parseConfigFile(watchPath)
				if parseErr == nil {
					data.TopoInfo = newConfiguration
					lastMod = info.ModTime()
				}
			}
			time.Sleep(250 * time.Millisecond)
		}
	}()
}
