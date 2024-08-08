/*
 * Copyright (c) 2001-2005 The Regents of The University of Michigan
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#ifndef __CPU_EXETRACE_HH__
#define __CPU_EXETRACE_HH__

#include "base/output.hh"
#include "base/trace.hh"
#include "base/types.hh"
#include "cpu/static_inst.hh"
#include "cpu/thread_context.hh"
#include "debug/ExecEnable.hh"
#include "debug/ChampSimTrace.hh"
#include "params/ExeTracer.hh"
#include "sim/insttracer.hh"
#include <set>

namespace ChampsimTrace{
    // instruction format
    constexpr std::size_t NUM_INSTR_DESTINATIONS = 4;
    constexpr std::size_t NUM_INSTR_SOURCES = 6;
    
    struct input_instr {
      // instruction pointer or PC (Program Counter)
      unsigned long long ip = 0;
    
      // branch info
      unsigned char is_branch = 0;
      unsigned char branch_taken = 0;
    
      unsigned char destination_registers[NUM_INSTR_DESTINATIONS] = {}; // output registers
      unsigned char source_registers[NUM_INSTR_SOURCES] = {};           // input registers
    
      unsigned long long destination_memory[NUM_INSTR_DESTINATIONS] = {}; // output memory
      unsigned long long source_memory[NUM_INSTR_SOURCES] = {};           // input memory

      unsigned char flags = 0;
      unsigned char pref = 0;
    };

    template <typename T>
    void WriteToSet(T* begin, T* end, T r)
    {
      auto set_end = std::find(begin, end, 0);
      if(set_end == end){
          //DPRINTFN("reached end\n");
          return;
      }
      auto found_reg = std::find(begin, set_end, r); // check to see if this register is already in the list
      *found_reg = r;
    }

}


namespace gem5
{

class ThreadContext;

namespace Trace {

class ExeTracerRecord : public InstRecord
{
  public:
    typedef ChampsimTrace::input_instr ChampSimTraceInst;
    ChampSimTraceInst cTraceInst; 

    ExeTracerRecord(Tick _when, ThreadContext *_thread,
               const StaticInstPtr _staticInst, TheISA::PCState _pc,
               const StaticInstPtr _macroStaticInst = NULL)
        : InstRecord(_when, _thread, _staticInst, _pc, _macroStaticInst)
    {
        cTraceInst = {};
    }

    void traceInst(const StaticInstPtr &inst, bool ran);

    void dumpCmpInst(const StaticInstPtr &inst, bool ran);

    void dump();

    void dumpNopInst(std::vector<Addr> &addrList, bool prevSquashed);
};

class ExeTracer : public InstTracer
{
  public:
    typedef ExeTracerParams Params;
    ExeTracer(const Params &params) : InstTracer(params)
    {
        traceOut.open(simout.directory()+ "/champsim_trace",std::ios_base::binary | std::ios_base::trunc);
    }

    InstRecord *
    getInstRecord(Tick when, ThreadContext *tc,
            const StaticInstPtr staticInst, TheISA::PCState pc,
            const StaticInstPtr macroStaticInst = NULL)
    {
        if (!(debug::ExecEnable || debug::ChampSimTrace))
            return NULL;

        return new ExeTracerRecord(when, tc,
                staticInst, pc, macroStaticInst);
    }
};


} // namespace Trace
} // namespace gem5

#endif // __CPU_EXETRACE_HH__
