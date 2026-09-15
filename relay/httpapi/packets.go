package httpapi

import "github.com/D10Scot/Dispatcharr/relay/buffer"

// signalPacket is apps/proxy/live_proxy/utils.py:71-98's create_ts_packet:
// one 188-byte packet on the null PID (0x1FFF) -- sync byte, PID high bits
// 0x1F, PID low bits 0xFF, and byte 3 left ZERO, which is what Python
// writes, an adaptation-field-control value of "reserved" that every player
// this project has met discards as a null packet -- with an optional message
// in the payload from byte 4, cut at 180. The keepalive and the error packet
// are the same packet with and without a message; the error PID is the same
// PID (:87-92 sets both branches to 0x1FFF).
func signalPacket(message string) []byte {
	packet := make([]byte, buffer.TSPacketSize)
	packet[0] = 0x47
	packet[1] = 0x1F
	packet[2] = 0xFF
	if message != "" {
		copy(packet[4:4+180], message)
	}
	return packet
}
