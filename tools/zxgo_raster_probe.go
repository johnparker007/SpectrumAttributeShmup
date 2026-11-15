// Run from the extracted zx_go v1.13.0 module. This program only uses the
// headless test harness. The portable toolchain does not need a GUI driver.
package main

import (
	"encoding/json"
	"flag"
	"log"
	"os"

	"github.com/conorarmstrong/zx_go/pkg/roms"
	"github.com/conorarmstrong/zx_go/pkg/testharness"
)

type event struct {
	Model  string `json:"model"`
	Loops  int    `json:"loops,omitempty"`
	Frame  int    `json:"frame"`
	Tstate uint64 `json:"tstate"`
	PC     uint16 `json:"pc"`
	Value  *byte  `json:"value,omitempty"`
}

func main() {
	probe := flag.Bool("probe", false, "trace the two raster probe variants instead of the stock engine")
	align := flag.Bool("align-int", false, "place INT assertion at T-state zero for the ZEsarUX comparison")
	memoryContention := flag.Bool("mem-contention", true, "apply per-access memory contention")
	flag.Parse()
	if flag.NArg() != 2 {
		log.Fatal("pass the 128K and +2A engine snapshots, or the 1079 and 1080 loop snapshots with -probe")
	}

	output := json.NewEncoder(os.Stdout)
	emit := func(entry event) {
		if err := output.Encode(entry); err != nil {
			log.Fatal(err)
		}
	}
	models := []struct {
		name string
		kind roms.SpectrumModel
	}{{"128k", roms.Model128K}, {"plus2a", roms.ModelPlus2A}}
	for index, model := range models {
		if *probe {
			for offset := 0; offset < 2; offset++ {
				trace(model.name, model.kind, flag.Arg(offset), 1079+offset, *align, *memoryContention, emit)
			}
		} else {
			trace(model.name, model.kind, flag.Arg(index), 0, *align, *memoryContention, emit)
		}
	}
}

func trace(name string, model roms.SpectrumModel, snapshot string, loops int, align, memoryContention bool, emit func(event)) {
	harness, err := testharness.New(model)
	if err != nil {
		log.Fatal(err)
	}
	if err := harness.LoadSnapshot(snapshot); err != nil {
		log.Fatal(err)
	}
	cpu := harness.CPU()
	cpu.MemContend = memoryContention
	if align {
		cpu.IntAssertTstate = 0
	}

	frame, frames := 0, 8
	if loops == 0 {
		frames = 32
		cpu.AddPreFetchHook("ringo8-boundaries", func(pc uint16) {
			switch pc {
			case 0x801D, 0x8E2D, 0x9B30, 0x802F, 0x9B2C, 0x9B45, 0xA5F0, 0xA5FD, 0xA5F6, 0xA5E9:
				emit(event{name, 0, frame, cpu.Tstates(), pc, nil})
			}
		})
	}
	harness.ULA().SetPortTracer(func(port uint16, value byte, write, _ bool) {
		if write && port == 0x7FFD {
			emit(event{name, loops, frame, cpu.Tstates(), cpu.PC - 2, &value})
		}
	})
	for frame = 0; frame < frames; frame++ {
		// Harness.RunFrames uses the 48K default. Use this model's period.
		cpu.ExecuteFrame(roms.FrameTStates(model))
	}
}
