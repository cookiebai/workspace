package main

import (
	"NodeDaemon/config"
	"NodeDaemon/pkg/synchronizer"
	opensnUtils "NodeDaemon/utils"
	"capture/utils"
	"fmt"
	"image"
	"image/color"
	"image/color/palette"
	"image/draw"
	"image/gif"
	"os"
	"os/signal"
	"syscall"

	"github.com/fogleman/gg"
	"github.com/google/gopacket"
)

type TimeStampSize struct {
	TimeStampSize uint64
	Size          uint64
}

var ThisNodeIndex = GetThisNodeIndex()

const CHANNEL_BUFFER_SIZE = 4096
const GIF_GAP_TEN_MILLISECOND = 25

var PARRALLEL_THREAD_NUM = 8

// var SrcIP string = "10.0.0.1"
// ping -s 20000 -i 0.0001 10.0.1.202
var DstIP string = "10.4.0.33"
var timestampSizeArray []map[string]uint64
var timestampArray []uint64

func GetThisNodeIndex() int {
	return 0
}

func isInPalette(p color.Palette, c color.Color) int {
	ret := -1
	for i, v := range p {
		if v == c {
			return i
		}
	}
	return ret
}

func getPalette(m image.Image) color.Palette {
	p := color.Palette{color.RGBA{0x00, 0x00, 0x00, 0x00}}
	p9 := color.Palette(palette.Plan9)
	b := m.Bounds()
	black := false
	for y := b.Min.Y; y < b.Max.Y; y++ {
		for x := b.Min.X; x < b.Max.X; x++ {
			c := m.At(x, y)
			cc := p9.Convert(c)
			if cc == p9[0] {
				black = true
			}
			if isInPalette(p, cc) == -1 {
				p = append(p, cc)
			}
		}
	}
	if len(p) < 256 && black == true {
		p[0] = color.RGBA{0x00, 0x00, 0x00, 0x00} // transparent
		p = append(p, p9[0])
	}
	return p
}

func main() {
	config.InitConfig("../../daemon/opensn-daemon/config/config.json")
	fmt.Printf("Etcd Addr is %s, Port is %d \n", config.GlobalConfig.Dependency.EtcdAddr, config.GlobalConfig.Dependency.EtcdPort)
	opensnUtils.InitEtcdClient(config.GlobalConfig.Dependency.EtcdAddr, config.GlobalConfig.Dependency.EtcdPort)
	fmt.Printf("This node index is %d\n", ThisNodeIndex)
	linkList, err := synchronizer.GetLinkList(ThisNodeIndex)

	if err != nil {
		fmt.Println(err)
		return
	}
	linkCaptureLengthMap := make(map[string]uint64)
	fmt.Printf("Get %d links\n", len(linkList))
	channel := make(chan utils.PacketWithInterface, CHANNEL_BUFFER_SIZE)
	endChan := make(chan int)
	for _, linkInfo := range linkList {
		utils.StartAsyncCaptureInterfaceWithFilter(linkInfo.GetLinkID(), func(packet gopacket.Packet) bool {
			if packet == nil || packet.NetworkLayer() == nil {
				return false
			}
			// networkHeader := packet.NetworkLayer()
			//Check Src IP == SRC_IP_ARRAY and Dst IP == DST_IP_ARRAY
			// if networkHeader.NetworkFlow().Src().String() == SrcIP &&
			// 	networkHeader.NetworkFlow().Dst().String() == DstIP {
			// 	return true
			// }
			return packet.NetworkLayer().NetworkFlow().Dst().String() == DstIP
		}, channel, endChan)
	}
	// Receice Ctrl+C signal to stop the capture

	osSignal := make(chan os.Signal, 1)
	signal.Notify(osSignal, os.Interrupt, syscall.SIGTERM)

loop:
	for {

		select {
		case packet := <-channel:
			fmt.Println(packet)
			linkCaptureLengthMap[packet.InterfaceName] += uint64(packet.Packet.Metadata().CaptureInfo.Length)
			if len(timestampSizeArray) == 0 {
				timestampSizeArray = append(timestampSizeArray, map[string]uint64{})
				timestampArray = append(timestampArray, uint64(packet.Packet.Metadata().Timestamp.UnixMilli()/GIF_GAP_TEN_MILLISECOND/10))
				timestampSizeArray[0][packet.InterfaceName] = uint64(packet.Packet.Metadata().CaptureInfo.Length)
			} else if uint64(packet.Packet.Metadata().Timestamp.UnixMilli())/GIF_GAP_TEN_MILLISECOND/10 > timestampArray[len(timestampSizeArray)-1] {
				timestampSizeArray = append(timestampSizeArray, map[string]uint64{})
				timestampArray = append(timestampArray, uint64(packet.Packet.Metadata().Timestamp.UnixMilli()/GIF_GAP_TEN_MILLISECOND/10))
				timestampSizeArray[0][packet.InterfaceName] = uint64(packet.Packet.Metadata().CaptureInfo.Length)
			} else {
				timestampSizeArray[len(timestampSizeArray)-1][packet.InterfaceName] += uint64(packet.Packet.Metadata().CaptureInfo.Length)
			}
		case <-osSignal:
			fmt.Println("Receive Ctrl+C signal")
			// close(endChan)
			break loop
		}
	}

	close(channel)
	fmt.Println("Capture stopped")
	for k, v := range linkCaptureLengthMap {
		fmt.Printf("Link %s capture %d bytes\n", k, v)
	}
	instanceList, err := synchronizer.GetInstanceList(ThisNodeIndex)
	if err != nil {
		fmt.Println(err)
		return
	}
	im := utils.DrawNetworkPayloadGraph(instanceList, linkList, linkCaptureLengthMap)
	gg.SavePNG("network_payload.png", im)
	nframes := len(timestampSizeArray)
	ann := gif.GIF{LoopCount: nframes}
	for range timestampSizeArray {
		ann.Delay = append(ann.Delay, GIF_GAP_TEN_MILLISECOND)
		ann.Image = append(ann.Image, nil)
	}
	wg := utils.ForEachWithThreadPool[map[string]uint64](func(index int, v map[string]uint64) {

		fr := utils.DrawNetworkPayloadGraph(instanceList, linkList, v)
		pl := image.NewPaletted(fr.Bounds(), getPalette(fr))
		draw.Draw(pl, pl.Rect, fr, image.Point{}, draw.Src)
		ann.Image[index] = pl
		fmt.Printf("Generate frame %d of %d\n", index, nframes)

	}, timestampSizeArray, PARRALLEL_THREAD_NUM)
	wg.Wait()
	f, _ := os.OpenFile("network_payload_ann.gif", os.O_WRONLY|os.O_CREATE, 0777)
	defer f.Close()
	gif.EncodeAll(f, &ann)

}
