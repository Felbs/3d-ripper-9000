"""Minimal DWARF 1 reader (CodeWarrior .debug): structs with member offsets, typedef/base names."""
import struct, sys, pickle, collections
TAG={0x01:"padding",0x02:"array",0x03:"class",0x04:"entry_point",0x05:"enum",0x06:"formal_parameter",0x08:"global_subroutine",0x09:"global_variable",0x0a:"label",0x0b:"lexical_block",0x0d:"local_variable",0x0e:"member",0x0f:"pointer",0x10:"reference",0x11:"compile_unit",0x12:"string",0x13:"structure",0x15:"subroutine",0x16:"typedef",0x17:"union",0x18:"unspec_params",0x19:"variant",0x1a:"common_block",0x1b:"common_inclusion",0x1c:"inheritance",0x1d:"inlined_subroutine",0x1e:"module",0x1f:"ptr_to_member",0x20:"set",0x21:"subrange",0x22:"with"}
AT={0x0010:"sibling",0x0020:"location",0x0030:"name",0x0050:"fund_type",0x0060:"mod_fund_type",0x0070:"user_def_type",0x0080:"mod_u_d_type",0x0090:"ordering",0x00a0:"subscr_data",0x00b0:"byte_size",0x00c0:"bit_offset",0x00d0:"bit_size",0x00f0:"element_list",0x0100:"stmt_list",0x0110:"low_pc",0x0120:"high_pc",0x0130:"language",0x0140:"member",0x0150:"discr",0x0160:"discr_value",0x0190:"string_length",0x01a0:"common_reference",0x01b0:"comp_dir",0x01c0:"const_value",0x01d0:"containing_type",0x01e0:"default_value",0x0200:"inline",0x0210:"is_optional",0x0220:"lower_bound",0x0260:"producer",0x0270:"prototyped",0x0280:"return_addr",0x0290:"start_scope",0x02b0:"stride_size",0x02c0:"upper_bound",0x02e0:"virtual"}
def parse(dbg):
    dies=[]; p=0; n=len(dbg)
    while p+6<=n:
        length=struct.unpack_from(">I",dbg,p)[0]
        if length<8:
            p+=length if length>=4 else 4; continue
        tag=struct.unpack_from(">H",dbg,p+4)[0]
        q=p+6; end=p+length; attrs={}
        while q+2<=end:
            a=struct.unpack_from(">H",dbg,q)[0]; q+=2; form=a&0xf; name=AT.get(a&0xfff0, hex(a&0xfff0))
            if form==1: v=struct.unpack_from(">I",dbg,q)[0]; q+=4        # ADDR
            elif form==2: v=struct.unpack_from(">I",dbg,q)[0]; q+=4      # REF
            elif form==3: l=struct.unpack_from(">H",dbg,q)[0]; v=dbg[q+2:q+2+l]; q+=2+l   # BLOCK2
            elif form==4: l=struct.unpack_from(">I",dbg,q)[0]; v=dbg[q+4:q+4+l]; q+=4+l   # BLOCK4
            elif form==5: v=struct.unpack_from(">H",dbg,q)[0]; q+=2      # DATA2
            elif form==6: v=struct.unpack_from(">I",dbg,q)[0]; q+=4      # DATA4
            elif form==7: v=struct.unpack_from(">Q",dbg,q)[0]; q+=8      # DATA8
            elif form==8: e=dbg.find(b"\0",q); v=dbg[q:e].decode("latin-1"); q=e+1   # STRING
            else: break
            attrs[name]=v
        dies.append((p, tag, attrs)); p=end
    return dies
def loc_offset(block):
    # DWARF1 location: OP_CONST(3) u32, OP_ADD(4)
    if isinstance(block,(bytes,bytearray)) and len(block)>=5 and block[0] in (3,4): return struct.unpack_from(">I",block,1)[0]
    return None
if __name__=="__main__":
    elf=open(sys.argv[1],"rb").read()
    shoff=struct.unpack_from(">I",elf,0x20)[0]; shentsize,shnum,shstrndx=struct.unpack_from(">HHH",elf,0x2e)
    secs=[struct.unpack_from(">IIIIIIIIII",elf,shoff+i*shentsize) for i in range(shnum)]
    st=secs[shstrndx]; names=elf[st[4]:st[4]+st[5]]
    dbg=[s for s in secs if names[s[0]:names.find(b"\0",s[0])]==b".debug"][0]
    d=elf[dbg[4]:dbg[4]+dbg[5]]
    dies=parse(d); print(len(dies), "dies")
    # build struct map: name -> [(offset, membername)]
    structs={}; cur=None
    for off,tag,attrs in dies:
        t=TAG.get(tag)
        if t in("structure","class","union") and "name" in attrs:
            cur=attrs["name"]; structs.setdefault(cur,{"size":attrs.get("byte_size"),"members":[]})
        elif t in ("member","local_variable") and cur and "member" in attrs:
            structs[cur]["members"].append((loc_offset(attrs.get("location")), attrs.get("name"), attrs.get("fund_type"), attrs.get("user_def_type")))
        elif t in ("global_subroutine","subroutine","compile_unit"): cur=None
    pickle.dump(structs, open(sys.argv[2],"wb"))
    for want in sys.argv[3:]:
        s=structs.get(want)
        if not s: print("no", want); continue
        print(f"=== {want} size {s['size']}")
        for o,n,ft,ud in s["members"]: print(f"  +{o if o is not None else '?':>4} {n} ft={ft} ud={ud}")
