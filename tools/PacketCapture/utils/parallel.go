package utils

import "sync"

func ForEachWithThreadPool[T any](callable func(index int, v T), array []T, maxRoutine int) *sync.WaitGroup {
	chanBuf := make(chan bool, maxRoutine)
	wg := new(sync.WaitGroup)
	for i, v := range array {
		chanBuf <- true
		wg.Add(1)
		go func(i int, v T) {
			callable(i, v)
			<-chanBuf
			wg.Done()
		}(i, v)
	}
	return wg
}
