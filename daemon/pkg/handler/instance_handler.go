package handler

import (
	"NodeDaemon/model"
	"NodeDaemon/model/ginmodel"
	"NodeDaemon/pkg/synchronizer"
	"NodeDaemon/utils"
	"bytes"
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"
)

func AddInstanceHandler(ctx *gin.Context) {
	var req ginmodel.AddInstanceRequest
	if err := ctx.Bind(&req); err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}

	// err := synchronizer.AddInstance(req.NodeIndex, req.Instance)
	// if err != nil {
	// 	jsonResp := ginmodel.JsonResp{
	// 		Code:    -1,
	// 		Message: fmt.Sprintf("Add Instance Error: %s", err.Error()),
	// 	}
	// 	ctx.JSON(http.StatusInternalServerError, jsonResp)
	// 	return
	// }
	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
	}
	ctx.JSON(http.StatusOK, jsonResp)
}

func DelInstanceHandler(ctx *gin.Context) {
	var req ginmodel.SingleInstanceRequest
	if err := ctx.Bind(&req); err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}

	instance, err := synchronizer.GetInstanceInfo(req.NodeIndex, req.InstanceID)

	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Get Instance Info Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}

	for _, connection := range instance.Connections {
		if connection.EndNodeIndex == instance.NodeIndex {
			err = synchronizer.RemoveLink(instance.NodeIndex, connection.LinkID)
			if err != nil {
				errMsg := fmt.Sprintf("Delete Link %s Error: %s", connection.LinkID, err.Error())
				logrus.Error(errMsg)
			}
		} else {
			err = synchronizer.RemoveLink(connection.EndNodeIndex, connection.LinkID)
			if err != nil {
				errMsg := fmt.Sprintf("Delete Link %s Error: %s", connection.LinkID, err.Error())
				logrus.Error(errMsg)
			}
			err = synchronizer.RemoveLink(instance.NodeIndex, connection.LinkID)
			if err != nil {
				errMsg := fmt.Sprintf("Delete Link %s Error: %s", connection.LinkID, err.Error())
				logrus.Error(errMsg)
			}
		}
	}
	err = synchronizer.RemoveInstance(req.NodeIndex, req.InstanceID)
	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Remove Instance Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}
	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
	}
	ctx.JSON(http.StatusOK, jsonResp)
}

func GetInstanceListHandler(ctx *gin.Context) {
	var req ginmodel.GetInstanceListRequest
	var instanceList []*model.Instance
	var respData []ginmodel.InstanceAbstract

	if err := ctx.Bind(&req); err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}
	nodes, err := synchronizer.GetNodeList()
	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Get NodeList Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}

	for _, node := range nodes {
		nodeInstanceList, err := synchronizer.GetInstanceList(node.NodeIndex)
		if err != nil {
			errMsg := fmt.Sprintf("Get Instance List of Node %d Error: %s", node.NodeIndex, err.Error())
			logrus.Error(errMsg)
			continue
		}
		for _, instance := range nodeInstanceList {
			if req.KeyWord == "" || strings.Contains(instance.Name, req.KeyWord) {
				instanceList = append(instanceList, instance)
			}
		}
	}

	startIndex := 0
	endIndex := len(instanceList)

	if req.PageIndex >= 0 && req.PageSize > 0 {
		startIndex = req.PageSize * req.PageIndex
		endIndex = startIndex + req.PageSize
	}

	for i := startIndex; i < endIndex && i < len(instanceList); i++ {
		instance := instanceList[i]
		respData = append(respData, ginmodel.InstanceAbstract{
			InstanceID: instance.InstanceID,
			Name:       instance.Name,
			NodeIndex:  instance.NodeIndex,
			Type:       instance.Type,
			Start:      instance.Start,
			Extra:      instance.Extra,
		})
	}

	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
		Data:    respData,
	}
	ctx.JSON(http.StatusOK, jsonResp)

}

func GetInstanceInfoHandler(ctx *gin.Context) {
	var respData ginmodel.InstanceInfo

	instanceID := ctx.Param("instance_id")
	nodeIndexStr := ctx.Param("node_index")
	nodeIndex, err := strconv.Atoi(nodeIndexStr)
	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Node Index: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}
	instance, err := synchronizer.GetInstanceInfo(nodeIndex, instanceID)

	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Get Instance Info Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}

	respData = ginmodel.InstanceInfo{
		InstanceID:    instance.InstanceID,
		Name:          instance.Name,
		Type:          instance.Type,
		Start:         instance.Start,
		Extra:         instance.Extra,
		Connections:   instance.Connections,
		Image:         instance.Image,
		ResourceLimit: instance.Resource,
		NodeIndex:     instance.NodeIndex,
	}

	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
		Data:    respData,
	}
	ctx.JSON(http.StatusOK, jsonResp)
}

func StartInstanceHander(ctx *gin.Context) {
	var req ginmodel.SingleInstanceRequest
	if err := ctx.Bind(&req); err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}

	err := synchronizer.UpdateInstanceInfo(req.NodeIndex, req.InstanceID, func(i *model.Instance) error {
		i.Start = true
		return nil
	})
	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Start Instance Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}
	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
	}
	ctx.JSON(http.StatusOK, jsonResp)
}

func ExecInstanceHandler(ctx *gin.Context) {
	var req ginmodel.ExecInstanceRequest
	if err := ctx.BindJSON(&req); err != nil {
		ctx.JSON(http.StatusBadRequest, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		})
		return
	}

	instance, err := synchronizer.GetInstanceInfo(req.NodeIndex, req.InstanceID)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Get Instance Info Error: %s", err.Error()),
		})
		return
	}

	containerID := fmt.Sprintf("%s_%s", instance.Type, instance.InstanceID)
	cmd := append([]string{req.Command}, req.Args...)

	execResp, err := utils.DockerClient.ContainerExecCreate(context.Background(), containerID, types.ExecConfig{
		Cmd:          cmd,
		AttachStdout: !req.Detach,
		AttachStderr: !req.Detach,
	})
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Exec Create Error: %s", err.Error()),
		})
		return
	}

	if req.Detach {
		if err := utils.DockerClient.ContainerExecStart(context.Background(), execResp.ID, types.ExecStartCheck{Detach: true}); err != nil {
			ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
				Code:    -1,
				Message: fmt.Sprintf("Exec Start Error: %s", err.Error()),
			})
			return
		}
		ctx.JSON(http.StatusOK, ginmodel.JsonResp{Code: 0, Message: "Success", Data: map[string]interface{}{"exit_code": 0}})
		return
	}

	hijack, err := utils.DockerClient.ContainerExecAttach(context.Background(), execResp.ID, types.ExecStartCheck{})
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Exec Attach Error: %s", err.Error()),
		})
		return
	}
	defer hijack.Close()

	var outBuf, errBuf bytes.Buffer
	if _, err := stdcopy.StdCopy(&outBuf, &errBuf, hijack.Reader); err != nil {
		ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Read Output Error: %s", err.Error()),
		})
		return
	}

	inspect, err := utils.DockerClient.ContainerExecInspect(context.Background(), execResp.ID)
	if err != nil {
		ctx.JSON(http.StatusInternalServerError, ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Exec Inspect Error: %s", err.Error()),
		})
		return
	}

	ctx.JSON(http.StatusOK, ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
		Data: map[string]interface{}{
			"exit_code": inspect.ExitCode,
			"output":    outBuf.String(),
		},
	})
}

func StopInstanceHandler(ctx *gin.Context) {
	var req ginmodel.SingleInstanceRequest
	if err := ctx.Bind(&req); err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Invalid Request Data: %s", err.Error()),
		}
		ctx.JSON(http.StatusBadRequest, jsonResp)
		return
	}

	err := synchronizer.UpdateInstanceInfo(req.NodeIndex, req.InstanceID, func(i *model.Instance) error {
		i.Start = false
		return nil
	})
	if err != nil {
		jsonResp := ginmodel.JsonResp{
			Code:    -1,
			Message: fmt.Sprintf("Stop Instance Error: %s", err.Error()),
		}
		ctx.JSON(http.StatusInternalServerError, jsonResp)
		return
	}
	jsonResp := ginmodel.JsonResp{
		Code:    0,
		Message: "Success",
	}
	ctx.JSON(http.StatusOK, jsonResp)
}
