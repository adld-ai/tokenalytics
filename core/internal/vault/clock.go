package vault

import "time"

// timeNowNano is a var so tests can make refs deterministic.
var timeNowNano = func() int64 { return time.Now().UnixNano() }
