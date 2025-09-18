package utils

import (
	"syscall"
	"unsafe"
)

type timespec struct {
	Sec  int64
	Nsec int64
}

func SetSystemTime(seconds int64, nanoseconds int64) error {
	ts := timespec{Sec: seconds, Nsec: nanoseconds}
	_, _, errno := syscall.Syscall(syscall.SYS_CLOCK_SETTIME, 0, uintptr(unsafe.Pointer(&ts)), 0)
	if errno != 0 {
		return errno
	}
	return nil
}
