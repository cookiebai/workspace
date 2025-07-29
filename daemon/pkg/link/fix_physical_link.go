package link

import (
	"NodeDaemon/data"
	"NodeDaemon/model"
	"NodeDaemon/share/key"
	"fmt"

	"github.com/sirupsen/logrus"
	"github.com/vishvananda/netlink"
)

const FixPhysicalLinkType = "fplink"

const (
	FPLinkDelayParameter     = "delay"
	FPLinkLossParameter      = "loss"
	FPLinkBandwidthParameter = "bandwidth"
)

var FixPhysLinkParameterMap = map[string]model.ParameterInfo{
	model.ConnectParameter: model.ConnectParameterInfo,
	FPLinkDelayParameter: {
		Name:           FPLinkDelayParameter,
		MinVal:         0,
		MaxVal:         1e10,
		DefinitionFrac: 1e9,
		DefaultVal:     0,
	},
	FPLinkLossParameter: {
		Name:           FPLinkLossParameter,
		MinVal:         0,
		MaxVal:         10000,
		DefinitionFrac: 10000,
		DefaultVal:     0,
	},
	FPLinkBandwidthParameter: {
		Name:           FPLinkBandwidthParameter,
		MinVal:         0,
		MaxVal:         1e10,
		DefinitionFrac: 1,
		DefaultVal:     0,
	},
}

// connection info [0] is the physical link, [1] is the virtual node
type FixPhysLink struct {
	model.LinkBase
}

func CreateFixPhysLinkObject(base model.LinkBase) *FixPhysLink {
	return &FixPhysLink{
		LinkBase: base,
	}
}

func (l *FixPhysLink) IsCreated() bool {
	_, err := netlink.LinkByName(l.LinkID)

	return err == nil
}

func (l *FixPhysLink) IsEnabled() bool {
	_, err := netlink.LinkByName(fmt.Sprintf("%s-%d", l.LinkID, 0))

	if err == nil {
		return true
	}
	_, err = netlink.LinkByName(fmt.Sprintf("%s-%d", l.LinkID, 1))
	return err == nil
}

func (l *FixPhysLink) Create() error {
	bridge := &netlink.Bridge{
		LinkAttrs: netlink.LinkAttrs{
			Name:   l.GetLinkID(),
			TxQLen: -1,
		},
	}

	err := netlink.LinkAdd(bridge)
	if err != nil {
		logrus.Errorf("Add Bridge Link %s Error: %s", bridge.Name, err.Error())
		return err
	}

	err = netlink.LinkSetUp(bridge)
	if err != nil {
		logrus.Errorf("Set Bridge Link %s Up Error: %s", bridge.Name, err.Error())
		return err
	}

	return err
}

func (l *FixPhysLink) Destroy() error {

	bridge, err := netlink.LinkByName(l.GetLinkID())
	if err != nil {
		err := fmt.Errorf("get bridge device from name %s error: %s", l.LinkID, err.Error())
		return err
	}
	err = netlink.LinkDel(bridge)
	if err != nil {
		err := fmt.Errorf("delete bridge device %s error: %s", l.LinkID, err.Error())
		return err
	}
	logrus.Infof("Distory Link %s, Type: Single Machine %s Success", l.LinkID, l.Type)
	return nil
}

func (l *FixPhysLink) Connect() error {
	if !l.IsEnabled() {
		logrus.Errorf("Connect %s and %s Error: %s is not enabled", l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID, l.LinkID)
		return fmt.Errorf("%s is not enabled", l.LinkID)
	}

	setLink, err := netlink.LinkByName(l.LinkID)
	if err != nil {
		err := fmt.Errorf("get sub device from name %s error: %s", l.LinkID, err.Error())
		return err
	}
	err = netlink.LinkSetUp(setLink)
	if err != nil {
		err := fmt.Errorf("set sub device %s up error: %s", l.LinkID, err.Error())
		return err
	}

	logrus.Infof(
		"Connect Link %s Between %s and %s Success",
		l.GetLinkID(),
		l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID,
	)
	return nil
}
func (l *FixPhysLink) Disconnect() error {
	if !l.IsEnabled() {
		logrus.Errorf("Connect %s and %s Error: %s is not enabled", l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID, l.LinkID)
		return fmt.Errorf("%s is not enabled", l.LinkID)
	}

	setLink, err := netlink.LinkByName(l.LinkID)
	if err != nil {
		err := fmt.Errorf("get sub device from name %s error: %s", l.LinkID, err.Error())
		return err
	}
	err = netlink.LinkSetDown(setLink)
	if err != nil {
		err := fmt.Errorf("set sub device %s down error: %s", setLink.Attrs().Name, err.Error())
		return err
	}

	logrus.Infof(
		"Disconnect Link %s Between %s and %s Success",
		l.GetLinkID(),
		l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID,
	)
	return nil
}

func (l *FixPhysLink) enableSameMachine(brIndex int) error {

	brLink, err := netlink.LinkByIndex(brIndex)
	if err != nil {
		logrus.Errorf("Get Bridge Link %s Error: %s", l.LinkID, err.Error())
		return err
	}

	physLink, err := netlink.LinkByName(l.EndInfos[0].InstanceID)

	if err != nil {
		logrus.Errorf("Get Physical Link %s Error: %s", l.LinkID, err.Error())
		return err
	}

	err = netlink.LinkSetName(physLink, fmt.Sprintf("%s-%d", l.GetLinkID(), 0))

	if err != nil {
		logrus.Errorf("Set Physical Link %s Alias %s Error: %s", l.EndInfos[0].InstanceID, l.LinkID, err.Error())
		return err
	}

	err = netlink.LinkSetMaster(physLink, brLink)
	if err != nil {
		logrus.Errorf("Set Physical Link %s Master Bridge %s Error: %s", l.EndInfos[0].InstanceID, l.LinkID, err.Error())
		return err
	}

	err = netlink.LinkSetUp(physLink)
	if err != nil {
		logrus.Errorf("Set Physical Link %s Up Error: %s", l.EndInfos[0].InstanceID, err.Error())
		return err
	}

	vEndInfo := l.EndInfos[1]
	instancePid := data.WatchInstancePid(vEndInfo.InstanceID)
	veth := &netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name:        fmt.Sprintf("%s-%d", l.GetLinkID(), 1),
			MasterIndex: brIndex,
		},
		PeerName:      l.GetLinkID(),
		PeerNamespace: netlink.NsPid(instancePid),
	}

	err = netlink.LinkAdd(veth)
	if err != nil {
		logrus.Errorf("Add VethLink Peer Link %v Error: %s", *l, err.Error())
		return err
	}
	err = netlink.LinkSetUp(veth)
	if err != nil {
		logrus.Errorf("Set VethLink Peer Link %v Up Error: %s", *l, err.Error())
		return err
	}

	return nil
}

func (l *FixPhysLink) enableCrossMachine(brIndex int) error {
	var targetNodeInfo *model.Node
	var err error
	for i, v := range l.EndInfos {
		if v.EndNodeIndex != key.NodeIndex {
			continue
		}
		targetNodeInfo, err = getNodeInfo(l.EndInfos[1-i].EndNodeIndex)
		if err != nil {
			return err
		}
	}
	for i, v := range l.EndInfos {
		if v.EndNodeIndex != key.NodeIndex {
			vxlanDev := netlink.Vxlan{
				LinkAttrs: netlink.LinkAttrs{
					Name:        fmt.Sprintf("%s-%d", l.GetLinkID(), i),
					TxQLen:      -1,
					MasterIndex: brIndex,
					MTU:         4096,
				},
				VxlanId:  l.LinkIndex,
				SrcAddr:  key.SelfNode.L3AddrV4,
				Group:    targetNodeInfo.L3AddrV4,
				Port:     4789,
				Learning: true,
				L2miss:   true,
				L3miss:   true,
			}

			logrus.Infof("Create Vxlan %v", vxlanDev)
			err = netlink.LinkAdd(&vxlanDev)
			if err != nil {
				logrus.Errorf("Add Vxlan Link %v Error: %s", *l, err.Error())
				continue
			}
			err = netlink.LinkSetUp(&vxlanDev)
			if err != nil {
				logrus.Errorf("Set Veth Peer Link %v Up Error: %s", *l, err.Error())
			}
		} else {
			if i != 0 {
				instancePid := data.WatchInstancePid(v.InstanceID)
				veth := &netlink.Veth{
					LinkAttrs: netlink.LinkAttrs{
						Name:        fmt.Sprintf("%s-%d", l.GetLinkID(), i),
						MasterIndex: brIndex,
					},
					PeerName:      l.GetLinkID(),
					PeerNamespace: netlink.NsPid(instancePid),
				}

				err = netlink.LinkAdd(veth)
				if err != nil {
					logrus.Errorf("Add Veth Peer Link %v Error: %s", *l, err.Error())
					continue
				}
				err = netlink.LinkSetUp(veth)
				if err != nil {
					logrus.Errorf("Set Veth Peer Link %v Up Error: %s", *l, err.Error())
				}
			} else {
				brLink, err := netlink.LinkByIndex(brIndex)
				if err != nil {
					logrus.Errorf("Get Bridge Link %s Error: %s", l.LinkID, err.Error())
					continue
				}

				physLink, err := netlink.LinkByName(l.EndInfos[0].InstanceID)

				if err != nil {
					logrus.Errorf("Get Physical Link %s Error: %s", l.LinkID, err.Error())
					continue
				}

				err = netlink.LinkSetName(physLink, fmt.Sprintf("%s-%d", l.GetLinkID(), 0))

				if err != nil {
					logrus.Errorf("Set Physical Link %s Alias %s Error: %s", l.EndInfos[0].InstanceID, l.LinkID, err.Error())
					continue
				}

				err = netlink.LinkSetMaster(physLink, brLink)
				if err != nil {
					logrus.Errorf("Set Physical Link %s Master Bridge %s Error: %s", l.EndInfos[0].InstanceID, l.LinkID, err.Error())
					continue
				}

				err = netlink.LinkSetUp(physLink)
				if err != nil {
					logrus.Errorf("Set Physical Link %s Up Error: %s", l.EndInfos[0].InstanceID, err.Error())
					continue
				}

			}
		}
	}

	return nil
}

func (l *FixPhysLink) Enable() error {

	logrus.Infof("Enabling Link %s, Type: Single Machine %s", l.LinkID, l.Type)
	var err error
	bridge, err := netlink.LinkByName(l.LinkID)

	if err != nil {
		return fmt.Errorf("enable link error: get master bridge error: %s", err.Error())
	}

	if l.CrossMachine {
		err = l.enableCrossMachine(bridge.Attrs().Index)
	} else {
		err = l.enableSameMachine(bridge.Attrs().Index)
	}

	if err != nil {
		return err
	}

	err = l.SetParameters(map[string]int64{}, l.Parameter)
	if err != nil {
		return err
	}

	return nil
}
func (l *FixPhysLink) Disable() error {

	for i, endInfo := range l.EndInfos {
		delLink, err := netlink.LinkByName(fmt.Sprintf("%s-%d", l.GetLinkID(), i))
		if err != nil {
			err := fmt.Errorf("get sub device from name %s error: %s", fmt.Sprintf("%s-%d", l.GetLinkID(), i), err.Error())
			logrus.Errorf("Disable Link %s Error: %s", l.LinkID, err.Error())
			continue
		}
		if l.EndInfos[0].EndNodeIndex == key.NodeIndex && i == 0 {
			err = netlink.LinkSetName(delLink, endInfo.InstanceID)
		} else {
			err = netlink.LinkDel(delLink)
		}
		if err != nil {
			err := fmt.Errorf("delete sub device %s error: %s", delLink.Attrs().Name, err.Error())
			logrus.Errorf("Disable Link %s Error: %s", l.LinkID, err.Error())
		}
	}
	logrus.Infof("Disable Link %s, Type: Single Machine %s Success", l.LinkID, l.Type)
	return nil
}

func (l *FixPhysLink) SetParameters(oldPara, newPara map[string]int64) error {
	dirtyConnect := false
	dirtyTbf := false
	dirtyNetem := false

	for paraName, paraValue := range newPara {
		if paraValue == oldPara[paraName] {
			logrus.Debugf("Value of %s for %s is not changed, ignore.", paraName, l.LinkID)
			continue
		}
		if _, ok := FixPhysLinkParameterMap[paraName]; !ok {
			logrus.Warnf("Unsupport Parameter %s for Link %s.", paraName, l.Type)
			continue
		}
		if paraValue != oldPara[paraName] {
			if paraName == model.ConnectParameter {
				dirtyConnect = true
			} else if paraName == FPLinkBandwidthParameter {
				dirtyTbf = true
			} else {
				dirtyNetem = true
			}
		}
	}

	if dirtyConnect {
		if newPara[model.ConnectParameter] == 0 {
			err := l.Disconnect()
			if err != nil {
				logrus.Errorf("Disconnect Link Between %s and %s Error: %s", l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID, err.Error())
				return err
			}
			return err
		} else {
			err := l.Connect()
			if err != nil {
				logrus.Errorf("Connect Link Between %s and %s Error: %s", l.EndInfos[0].InstanceID, l.EndInfos[1].InstanceID, err.Error())
				return err
			}
		}
	}

	for _, v := range l.EndInfos {
		if v.EndNodeIndex != key.NodeIndex {
			continue
		}

		if dirtyNetem {
			for i, v := range l.EndInfos {
				if v.EndNodeIndex != key.NodeIndex {
					continue
				}
				dev, err := netlink.LinkByName(fmt.Sprintf("%s-%d", l.GetLinkID(), i))
				if err != nil {
					logrus.Errorf("Update netem qdisc error: get link by name %s error: %s", fmt.Sprintf("%s-%d", l.GetLinkID(), i), err.Error())
					return err
				}
				netemInfo := netlink.NewNetem(
					NetemQdiscTemplate.QdiscAttrs,
					netlink.NetemQdiscAttrs{
						Latency: uint32(newPara[FPLinkDelayParameter]) + 1,
						Loss:    float32(newPara[FPLinkLossParameter]) / 100,
					},
				)
				netemInfo.LinkIndex = dev.Attrs().Index
				err = netlink.QdiscReplace(netemInfo)
				if err != nil {
					logrus.Errorf("Update netem qdisc error: %s", err.Error())
				}
			}
		}

		if dirtyTbf {
			for i, v := range l.EndInfos {
				if v.EndNodeIndex != key.NodeIndex {
					continue
				}
				dev, err := netlink.LinkByName(fmt.Sprintf("%s-%d", l.GetLinkID(), i))
				if err != nil {
					logrus.Errorf("Update tbf qdisc error: get link by name %s error: %s", fmt.Sprintf("%s-%d", l.GetLinkID(), i), err.Error())
					return err
				}
				tbfInfo := TbfQdiscTemplate
				tbfInfo.LinkIndex = dev.Attrs().Index
				tbfInfo.Limit = uint32(newPara[FPLinkBandwidthParameter])
				tbfInfo.Rate = uint64(newPara[FPLinkBandwidthParameter])
				tbfInfo.Buffer = uint32(newPara[FPLinkBandwidthParameter]) / 8
				err = netlink.QdiscReplace(&tbfInfo)
				if err != nil {
					logrus.Errorf("Update tbf qdisc error: %s", err.Error())
				}
			}
		}

	}

	return nil
}
