package utils

import (
	"NodeDaemon/model"
	"image"
	"math"
	"strconv"

	"github.com/fogleman/gg"
)

type Path struct {
	EdgeLinkPtr         model.Link
	EdgeSrcPtr          model.Instance
	EdgeDstPtr          model.Instance
	EdgePayloadStastics uint64
}

const (
	EX_ORIBIT_INDEX    = "OrbitIndex"
	EX_SATELLITE_INDEX = "SatelliteIndex"
	NODE_CANVAS_SIZE   = 20
	LINE_WIDTH         = 2
)

func DrawNetworkPayloadGraph(instanceList []*model.Instance, linkList []model.Link, linkPayloadMap map[string]uint64) image.Image {
	satellitePerOrbit := 0
	orbitNum := 0
	maxPayload := uint64(0)
	instancePositionMap := make(map[string][2]int)
	for _, instance := range instanceList {
		satelliteIndex, _ := strconv.Atoi(instance.Extra[EX_SATELLITE_INDEX])
		orbitIndex, _ := strconv.Atoi(instance.Extra[EX_ORIBIT_INDEX])
		if orbitIndex > orbitNum {
			orbitNum = orbitIndex
		}
		if satelliteIndex > satellitePerOrbit {
			satellitePerOrbit = satelliteIndex
		}
	}
	satellitePerOrbit += 1
	orbitNum += 1

	for _, instance := range instanceList {
		satelliteIndex, _ := strconv.Atoi(instance.Extra[EX_SATELLITE_INDEX])
		orbitIndex, _ := strconv.Atoi(instance.Extra[EX_ORIBIT_INDEX])
		instancePositionMap[instance.InstanceID] = [2]int{orbitIndex, satelliteIndex}
	}

	canvasSize := [2]int{(orbitNum)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE, (satellitePerOrbit)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE}
	canvas := gg.NewContext(canvasSize[0], canvasSize[1])
	canvas.SetRGB(1, 1, 1)
	canvas.Clear()
	for x := 0; x < orbitNum; x++ {
		for y := 0; y < satellitePerOrbit; y++ {
			canvas.DrawCircle(float64((x)*NODE_CANVAS_SIZE*2+NODE_CANVAS_SIZE/2*3), float64((y)*NODE_CANVAS_SIZE*2+NODE_CANVAS_SIZE/2*3), NODE_CANVAS_SIZE/2)
			canvas.SetRGB(255, 255, 255)
			canvas.Fill()
		}
	}

	for _, payload := range linkPayloadMap {
		if payload > maxPayload {
			maxPayload = payload
		}
	}

	for _, linkInfo := range linkList {

		srcInstanceID := linkInfo.GetLinkBasePtr().EndInfos[0].InstanceID
		dstInstanceID := linkInfo.GetLinkBasePtr().EndInfos[1].InstanceID

		srcInstancePostion := instancePositionMap[srcInstanceID]
		dstInstancePostion := instancePositionMap[dstInstanceID]

		x_src := srcInstancePostion[0]
		y_src := srcInstancePostion[1]
		x_dst := dstInstancePostion[0]
		y_dst := dstInstancePostion[1]

		if math.Abs(float64(x_src-x_dst)) > 1.5 {
			if x_src > x_dst {
				x_dst += orbitNum
			} else {
				x_src += orbitNum
			}
		}
		if math.Abs(float64(y_src-y_dst)) > 1.5 {
			if y_src > y_dst {
				y_dst += satellitePerOrbit
			} else {
				y_src += satellitePerOrbit
			}

		}

		srcPosition := [2]float64{float64((x_src)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE/2*3), float64((y_src)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE/2*3)}
		dstPosition := [2]float64{float64((x_dst)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE/2*3), float64((y_dst)*NODE_CANVAS_SIZE*2 + NODE_CANVAS_SIZE/2*3)}

		canvas.DrawLine(srcPosition[0], srcPosition[1], dstPosition[0], dstPosition[1])
		canvas.SetRGB(255-float64(linkPayloadMap[linkInfo.GetLinkID()]*255/(maxPayload+1)), float64(linkPayloadMap[linkInfo.GetLinkID()]*255/(maxPayload+1)), 0)
		canvas.SetLineWidth(LINE_WIDTH)
		canvas.Stroke()
	}

	return canvas.Image()

}
