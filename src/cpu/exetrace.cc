/*
 * Copyright (c) 2017, 2019 ARM Limited
 * All rights reserved
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
 *
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

#include "cpu/exetrace.hh"

#include <iomanip>
#include <sstream>

#include "base/loader/symtab.hh"
#include "config/the_isa.hh"
#include "cpu/base.hh"
#include "cpu/static_inst.hh"
#include "cpu/thread_context.hh"
#include "debug/ExecAll.hh"
#include "debug/FmtTicksOff.hh"
#include "enums/OpClass.hh"
#include "debug/ChampSimTraceDbg.hh"

namespace ChampsimTrace {
    void destReg(struct input_instr &t, int reg){
        WriteToSet<unsigned char>(t.destination_registers,
           t.destination_registers + NUM_INSTR_DESTINATIONS,
           reg);   
    }

    void srcReg(struct input_instr &t, int reg){
        WriteToSet<unsigned char>(t.source_registers,
           t.source_registers + NUM_INSTR_SOURCES,
           reg);   
    }
}

namespace gem5
{

namespace Trace {

#define BASE 3
#define FLAGS_REG 1
#define PC_REG 2
#define RSP_REG 7
#define NON_SPEC 0
#define SERIAL 1
#define SERIAL_AFTER 2
#define SERIAL_BEFORE 3
#define READ_BARRIER 4
#define WRITE_BARRIER 5
#define SQUASH_AFTER 6
#define SQUASHED 7

void
Trace::ExeTracerRecord::dumpCmpInst(const StaticInstPtr &inst, bool ran)
{
    if(!inst){
        return;
    }
    cTraceInst = {};
    Addr cur_pc = pc.instAddr();
    cTraceInst.ip = cur_pc; 

    DPRINTF(ChampSimTraceDbg, "PC: %llx squashed: %d\n", cur_pc, squashed);

    char brCode = 0;
    if(inst->isControl()){
        brCode |= 0x01;

        if(inst->isCondCtrl()){
            brCode |= ( 1 << 1);
        }

        if(inst->isDirectCtrl()){
            brCode |= ( 1 << 2);
        }

        if(inst->isCall()){
            brCode |= ( 1 << 3);
        }

        if(inst->isReturn()){
            brCode |= ( 1 << 4);
        }
    }
    char flags = 0;

    if(inst->isSerializing()){

        if(inst->isSerializeBefore()){
            flags |= (1 << SERIAL_BEFORE);
        }else if(inst->isSerializeAfter()){
            flags |= (1 << SERIAL_AFTER);
        }else{
            flags |= (1 << SERIAL);
        }
    }

    if(inst->isReadBarrier()){
        flags |= (1 << READ_BARRIER);
    }

    if(inst->isWriteBarrier()){
        flags |= (1 << WRITE_BARRIER);
    }

    if(inst->isNonSpeculative()){
        flags |= (1 << NON_SPEC);
    }

    if(inst->isSquashAfter()){
        flags |= (1 << SQUASH_AFTER);
    }

    if(squashed){
        flags |= (1 << SQUASHED);
    }

    //Write PC reg
    //if(inst->getName() == "wrip" || inst->getName() == "wripi"){
    //   ChampsimTrace::destReg(cTraceInst, PC_REG);

    //   if(inst->getName() == "wrip"){
    //       //Direct Branch
    //       if(inst->isCall()){
    //           //Reads SP IP
    //           //Writes SP IP
    //           ChampsimTrace::srcReg(cTraceInst, PC_REG);
    //           ChampsimTrace::srcReg(cTraceInst, RSP_REG);

    //           ChampsimTrace::destReg(cTraceInst, RSP_REG);
    //       }else if(inst->isCondCtrl()){
    //           //Reads IP FLAGS
    //           //Writes IP
    //           ChampsimTrace::srcReg(cTraceInst, PC_REG);
    //           ChampsimTrace::srcReg(cTraceInst, FLAGS_REG);
    //       }else{
    //           //Direct Jump
    //       }
    //   }else{
    //       //Indirect Branch
    //       if(inst->isReturn()){
    //           //Reads SP
    //           //Writes SP IP
    //           ChampsimTrace::srcReg(cTraceInst, RSP_REG);

    //           ChampsimTrace::destReg(cTraceInst, RSP_REG);
    //       }else if(inst->isCall()){
    //           //Reads others
    //           //Reads SP IP
    //           //Writes SP IP
    //           ChampsimTrace::srcReg(cTraceInst, PC_REG);
    //           ChampsimTrace::srcReg(cTraceInst, RSP_REG);

    //           ChampsimTrace::destReg(cTraceInst, RSP_REG);

    //           for(int i = 0; i < inst->numSrcRegs(); i++){
    //               ChampsimTrace::srcReg(cTraceInst, i + BASE);
    //           }
    //       }else{
    //           //Reads others
    //           for(int i = 0; i < inst->numSrcRegs(); i++){
    //               ChampsimTrace::srcReg(cTraceInst, i + BASE);
    //           }
    //       }
    //   }
    //} else{

    int src_regs=0;
    int dest_regs=0;

    bool found_flag = false;
        for(int i = 0; i < inst->numSrcRegs(); i++){
            if(inst->srcRegIdx(i).is(IntRegClass)){
                ChampsimTrace::WriteToSet<unsigned char>(cTraceInst.source_registers,
                  cTraceInst.source_registers + ChampsimTrace::NUM_INSTR_SOURCES,
                  inst->srcRegIdx(i).flatIndex() + BASE);   
                    src_regs++;
            }else if(inst->srcRegIdx(i).is(CCRegClass)){
                ChampsimTrace::WriteToSet<unsigned char>(cTraceInst.source_registers,
                  cTraceInst.source_registers + ChampsimTrace::NUM_INSTR_SOURCES,
                  1);   
                if(!found_flag){
                    src_regs++;
                    found_flag = true;
                }
            //}else{
            //    DPRINTFNR("%d ",inst->srcRegIdx(i).flatIndex());
            //    DPRINTFNR("%d ",inst->srcRegIdx(i));
            }
        }
        //DPRINTFNR("\n");
    found_flag = false;
        for(int i = 0; i < inst->numDestRegs(); i++){
            if(inst->destRegIdx(i).is(IntRegClass)){
                ChampsimTrace::WriteToSet<unsigned char>(cTraceInst.destination_registers,
                  cTraceInst.destination_registers + ChampsimTrace::NUM_INSTR_DESTINATIONS,
                  inst->destRegIdx(i).flatIndex() + BASE);   
                    dest_regs++;
            }else if(inst->destRegIdx(i).is(CCRegClass)){
                ChampsimTrace::WriteToSet<unsigned char>(cTraceInst.destination_registers,
                  cTraceInst.destination_registers + ChampsimTrace::NUM_INSTR_DESTINATIONS,
                  1);   
                if(!found_flag){
                    dest_regs++;
                    found_flag = true;
                }
            }
            //DPRINTFNR("%d ",inst->destRegIdx(i).flatIndex());
            //DPRINTFNR("%d ",inst->destRegIdx(i));
        }
    //}

    //DPRINTFNR("pc: 0x%llx src_regs %d dest_regs %d\n", cur_pc, src_regs, dest_regs);


    if(getMemValid()){
        if(inst->isLoad()){
             ChampsimTrace::WriteToSet<unsigned long long>(cTraceInst.source_memory,
               cTraceInst.source_memory + ChampsimTrace::NUM_INSTR_SOURCES,
               addr);   
         }else if (inst->isStore()){
             ChampsimTrace::WriteToSet<unsigned long long>(cTraceInst.destination_memory,
               cTraceInst.destination_memory + ChampsimTrace::NUM_INSTR_DESTINATIONS,
               addr);   
         }
    } 

    

   if(!inst->isMicroop() || inst->isLastMicroop()){
        if(inst->isControl()){
            cTraceInst.is_branch = brCode;
            //DPRINTFN("pc is %s size:%d branching: %d\n",pc,pc.size(), pc.branching());
            auto npc = pc;
            staticInst->advancePC(npc);

            if((pc.instAddr() + pc.size()) != npc.instAddr()){
                //cTraceInst.is_branch = 1;
                cTraceInst.branch_taken = 1;
            }
            //TODO: size check to figure out taken or not
        } 
    }

    cTraceInst.pref = 0;
    cTraceInst.flags = flags;
    auto &traceOut = thread->getCpuPtr()->getTracer()->traceOut;
    typename decltype(thread->getCpuPtr()->getTracer()->traceOut)::char_type buf[sizeof(ChampSimTraceInst)];
    std::memcpy(buf, &cTraceInst, sizeof(ChampSimTraceInst));
    traceOut.write(buf, sizeof(ChampSimTraceInst));
    //Dump to file here
}

void
Trace::ExeTracerRecord::traceInst(const StaticInstPtr &inst, bool ran)
{
    std::stringstream outs;

    const bool in_user_mode = thread->getIsaPtr()->inUserMode();
    if (in_user_mode && !debug::ExecUser)
        return;
    if (!in_user_mode && !debug::ExecKernel)
        return;

    if(squashed){
        outs << "==== ";
    }

    if (debug::ExecAsid) {
        outs << "A" << std::dec <<
            thread->getIsaPtr()->getExecutingAsid() << " ";
    }

    if (debug::ExecThread)
        outs << "T" << thread->threadId() << " : ";

    Addr cur_pc = pc.instAddr();
    loader::SymbolTable::const_iterator it;
    ccprintf(outs, "%#x", cur_pc);
    if (debug::ExecSymbol && (!FullSystem || !in_user_mode) &&
            (it = loader::debugSymbolTable.findNearest(cur_pc)) !=
                loader::debugSymbolTable.end()) {
        Addr delta = cur_pc - it->address;
        if (delta)
            ccprintf(outs, " @%s+%d", it->name, delta);
        else
            ccprintf(outs, " @%s", it->name);
    }

    if (inst->isMicroop()) {
        ccprintf(outs, ".%2d", pc.microPC());
    } else {
        ccprintf(outs, "   ");
    }

    ccprintf(outs, " : ");

    //
    //  Print decoded instruction
    //

    outs << std::setw(26) << std::left;
    outs << inst->disassemble(cur_pc, &loader::debugSymbolTable);

    
    if (ran) {
        outs << " : ";

        if (debug::ExecOpClass) {
            outs << enums::OpClassStrings[inst->opClass()] << " : ";
        }

        if (debug::ExecResult && !predicate) {
            outs << "Predicated False";
        }

        if (debug::ExecResult && data_status != DataInvalid) {
            switch (data_status) {
              case DataVec:
                ccprintf(outs, " D=%s", *data.as_vec);
                break;
              case DataVecPred:
                ccprintf(outs, " D=%s", *data.as_pred);
                break;
              default:
                ccprintf(outs, " D=%#018x", data.as_int);
                break;
            }
        }

        if (debug::ExecEffAddr && getMemValid())
            outs << " A=0x" << std::hex << addr;

        if (debug::ExecFetchSeq && fetch_seq_valid)
            outs << "  FetchSeq=" << std::dec << fetch_seq;

        if (debug::ExecCPSeq && cp_seq_valid)
            outs << "  CPSeq=" << std::dec << cp_seq;

        if (debug::ExecFlags) {
            outs << "  flags=(";
            inst->printFlags(outs, "|");
            outs << ")";
        }
    }

    //
    //  End of line...
    //
    outs << std::endl;

    Trace::getDebugLogger()->dprintf_flag(
        when, thread->getCpuPtr()->name(), "ExecEnable", "%s",
        outs.str().c_str());
    
 }

void
Trace::ExeTracerRecord::dumpNopInst(std::vector<Addr> &addrList, bool prevSquashed)
{
    for( auto prefAddr : addrList){
        cTraceInst = {};

        //zero initialize trace object
        //std::memset(&cTraceInst, 0,  sizeof(ChampSimTraceInst));
        Addr cur_pc = prefAddr;

        DPRINTF(ChampSimTraceDbg, "Writing dummy inst at PC: %llx prevSquashed %d\n", cur_pc, prevSquashed);

        char flags = 0;

        flags = prevSquashed;

        cTraceInst.ip = cur_pc; 
        cTraceInst.flags = flags;
        cTraceInst.is_branch = 0;
        cTraceInst.pref = 1;
        auto &traceOut = thread->getCpuPtr()->getTracer()->traceOut;
        typename decltype(thread->getCpuPtr()->getTracer()->traceOut)::char_type buf[sizeof(ChampSimTraceInst)];
        std::memcpy(buf, &cTraceInst, sizeof(ChampSimTraceInst));
        traceOut.write(buf, sizeof(ChampSimTraceInst));
    }
}

void
Trace::ExeTracerRecord::dump()
{
    /*
     * The behavior this check tries to achieve is that if ExecMacro is on,
     * the macroop will be printed. If it's on and microops are also on, it's
     * printed before the microops start printing to give context. If the
     * microops aren't printed, then it's printed only when the final microop
     * finishes. Macroops then behave like regular instructions and don't
     * complete/print when they fault.
     */
    if (debug::ExecMacro && staticInst->isMicroop() &&
        ((debug::ExecMicro &&
            macroStaticInst && staticInst->isFirstMicroop()) ||
            (!debug::ExecMicro &&
             macroStaticInst && staticInst->isLastMicroop()))) {
        traceInst(macroStaticInst, false);
    }
    if (debug::ExecMicro || !staticInst->isMicroop()) {
        traceInst(staticInst, true);
    }
    dumpCmpInst(staticInst, true);

}

} // namespace Trace
} // namespace gem5
