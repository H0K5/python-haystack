# -*- coding: utf-8 -*-
#
""" Win 7 heap structure - from LGPL metasm.
See docs/win32_heap for all supporting documentation.

The Heap Manager organizes its virtual memory using heap segments.
Distinction between reserved and committed memory.
Committing memory == mapping/backing the virtual memory.
Uncommitted memory is tracked using UCR entries and segments.

heap_size_including_ucr = heap.Counters.TotalMemoryReserved
segment_space +/- = heap.Segment.LastValidEntry -  heap.Segment.FirstEntry
committed_size = heap.Counters.TotalMemoryCommitted
sum_ucr_size = heap.Counters.TotalMemoryReserved - heap.Counters.TotalMemoryCommitted

heap.Counters.TotalMemoryReserved == heap.LastValidEntry - heap.BaseAddress
UCR and UCRSegments included.

Win7 Heap manager uses either Frontend allocator or Backend allocator.
Default Frontend allocator is Low Fragmentation Heap (LFH).

Chunks are allocated memory.
List of chunks allocated by the backend allocators are linked in
heap.segment.FirstValidEntry to LastValidEntry.
LFH allocations are in one big chunk of that list at heap.FrontEndHeap.

There can be multiple segment in one heap.
Each segment has a FirstEntry (chunk) and LastValidEntry.
FirstEntry <= chunks <= UCR < LastValidEntry

Heap is a segment.
Heap.SegmentList.Flink 0x580010L
Heap.SegmentList.Blink 0x1f00010L
Heap.SegmentList is at offset 0xa8

Heap.SegmentListEntry.Flink 0x1f00010L
Heap.SegmentListEntry.Blink 0x5800a8L
Heap.SegmentListEntry is at offset 0x10

    >>> hex(type(heap).SegmentList.offset)
    '0xa8'
    >>> hex(type(heap).SegmentListEntry.offset)
    '0x10'

So some segment pages ('children mapping') can be found by iterating Segments.
But in some case, the Heap mapping is punched with holes due to Uncommitted Pages. (memory acquisition problem??)
So there is only one segment, which LastValidEntry is > at the mapping end address
Is that a memory acquisition issue ?

Segment: UCRSegmentList
Heap: UCRList

You can fetch chunks tuple(address,size) with HEAP.get_chunks .

You can fetch ctypes segments with HEAP.get_segment_list
You can fetch free ctypes UCR segments with HEAP.get_UCR_segment_list
You can fetch a segment UCR segments with HEAP_SEGMENT.get_UCR_segment_list



"""

__author__ = "Loic Jaquemet"
__copyright__ = "Copyright (C) 2012 Loic Jaquemet"
__license__ = "GPL"
__maintainer__ = "Loic Jaquemet"
__email__ = "loic.jaquemet+python@gmail.com"
__status__ = "Production"


import ctypes
import logging

from haystack import model
from haystack.abc import interfaces
from haystack.allocators.win32 import winheap


log = logging.getLogger('win7heap')

############# Start methods overrides #################
# constraints are in constraints files

class Win7HeapValidator(winheap.WinHeapValidator):
    """
    this listmodel Validator will register know important list fields
    in the win7 HEAP,
    [ FIXME TODO and apply constraints ? ]
    and be used to validate the loading of these allocators.
    This class contains all helper functions used to parse the win7heap allocators.
    """

    def __init__(self, memory_handler, my_constraints, win7heap_module):
        if not isinstance(memory_handler, interfaces.IMemoryHandler):
            raise TypeError("Feed me a IMemoryHandler")
        if not isinstance(my_constraints, interfaces.IModuleConstraints):
            raise TypeError("Feed me a IModuleConstraints")
        super(Win7HeapValidator, self).__init__(memory_handler, my_constraints)
        self.win_heap = win7heap_module
        # LIST_ENTRY
        # the lists usually use end of mapping as a sentinel.
        # we have to use all mappings instead of heaps, because of a circular dependency
        #sentinels = set([mapping.end-0x10 for mapping in self._memory_handler.get_mappings()])
        sentinels = set()

        # sentinels = set() #set([mapping.end for mapping in self._memory_handler.get_mappings()])
        self.register_double_linked_list_record_type(self.win_heap.LIST_ENTRY, 'Flink', 'Blink', sentinels)
        self.register_single_linked_list_record_type(self.win_heap.SINGLE_LIST_ENTRY, 'Next', sentinels)

        # HEAP_SEGMENT
        # HEAP_SEGMENT.UCRSegmentList. points to HEAP_UCR_DESCRIPTOR.SegmentEntry.
        # HEAP_UCR_DESCRIPTOR.SegmentEntry. points to HEAP_SEGMENT.UCRSegmentList.
        # FIXME, use offset size base on self._target.get_word_size()
        self.register_linked_list_field_and_type(self.win_heap.HEAP_SEGMENT, 'UCRSegmentList', self.win_heap.HEAP_UCR_DESCRIPTOR, 'SegmentEntry') # offset = -8
        # as a facility HEAP contains HEAP_SEGMENT. But will also force parsing the list at HEAP loading time
        self.register_linked_list_field_and_type(self.win_heap.HEAP, 'UCRSegmentList', self.win_heap.HEAP_UCR_DESCRIPTOR, 'SegmentEntry') # offset = -8
        #HEAP_SEGMENT._listHead_ = [
        #        ('UCRSegmentList', HEAP_UCR_DESCRIPTOR, 'ListEntry', -8)]
        #HEAP_UCR_DESCRIPTOR._listHead_ = [ ('SegmentEntry', HEAP_SEGMENT, 'Entry')]

        # HEAP CommitRoutine encoded by a global key
        # The HEAP handle data structure includes a function pointer field called
        # CommitRoutine that is called when memory regions within the heap are committed.
        # Starting with Windows Vista, this field was encoded using a random value that
        # was also stored as a field in the HEAP handle data structure.

        #HEAP._listHead_ = [('SegmentList', HEAP_SEGMENT, 'SegmentListEntry', -16),
        #                   ('UCRList', HEAP_UCR_DESCRIPTOR, 'ListEntry', 0),
        #                   # for get_freelists. offset is sizeof(HEAP_ENTRY)
        #                   ('FreeLists', HEAP_FREE_ENTRY, 'FreeList', -8),
        #                   ('VirtualAllocdBlocks', HEAP_VIRTUAL_ALLOC_ENTRY, 'Entry', -8)]
        self.register_linked_list_field_and_type(self.win_heap.HEAP, 'SegmentList', self.win_heap.HEAP_SEGMENT, 'SegmentListEntry') # offset = -16
        self.register_linked_list_field_and_type(self.win_heap.HEAP, 'UCRList', self.win_heap.HEAP_UCR_DESCRIPTOR, 'ListEntry') # offset = 0
        # there is also a list of segments
        self.register_linked_list_field_and_type(self.win_heap.HEAP_UCR_DESCRIPTOR, 'SegmentEntry', self.win_heap.HEAP_SEGMENT, 'UCRSegmentList')
        # for get_freelists. offset is sizeof(HEAP_ENTRY)
        ## self.register_linked_list_field_and_type(self.win_heap.HEAP, 'FreeLists', self.win_heap.HEAP_FREE_ENTRY, 'FreeList') # offset =  -8
        if self._target.get_word_size() == 4:
            self.register_linked_list_field_and_type(self.win_heap.HEAP, 'FreeLists', self.win_heap.struct__HEAP_FREE_ENTRY_0_5, 'FreeList')
        else:
            self.register_linked_list_field_and_type(self.win_heap.HEAP, 'FreeLists', self.win_heap.struct__HEAP_FREE_ENTRY_0_2, 'FreeList')
        self.register_linked_list_field_and_type(self.win_heap.HEAP, 'VirtualAllocdBlocks', self.win_heap.HEAP_VIRTUAL_ALLOC_ENTRY, 'Entry')

        # LFH
        self.register_linked_list_field_and_type(self.win_heap.struct__LFH_HEAP, 'SubSegmentZones', self.win_heap.struct__LFH_BLOCK_ZONE, 'ListEntry')
        self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_LOCAL_DATA, 'CrtZone', self.win_heap.struct__LFH_BLOCK_ZONE, 'ListEntry')
        self.register_linked_list_field_and_type(self.win_heap.struct__LFH_BLOCK_ZONE, 'ListEntry', self.win_heap.struct__LFH_BLOCK_ZONE, 'ListEntry')
        self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_SUBSEGMENT, 'UserBlocks', self.win_heap.union__HEAP_USERDATA_HEADER_0, 'SFreeListEntry')
        if self._target.get_word_size() == 4:
            self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_SUBSEGMENT, 'SFreeListEntry', self.win_heap.struct__HEAP_FREE_ENTRY_0_5, 'FreeList')
        else:
            self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_SUBSEGMENT, 'SFreeListEntry', self.win_heap.struct__HEAP_FREE_ENTRY_0_2, 'FreeList')
        #self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_SUBSEGMENT, 'UserBlocks', self.win_heap.struct__HEAP_USERDATA_HEADER_0_0, 'SubSegment')
        #self.register_linked_list_field_and_type(self.win_heap.struct__HEAP_USERDATA_HEADER_0_0, 'SubSegment', self.win_heap.struct__HEAP_SUBSEGMENT, 'UserBlocks')

        # HEAP.SegmentList. points to SEGMENT.SegmentListEntry.
        # SEGMENT.SegmentListEntry. points to HEAP.SegmentList.
        # you need to ignore the Head in the iterator...

        # HEAP_UCR_DESCRIPTOR
        #HEAP_UCR_DESCRIPTOR._listMember_ = ['ListEntry']
        #HEAP_UCR_DESCRIPTOR._listHead_ = [    ('SegmentEntry', HEAP_SEGMENT, 'SegmentListEntry'),    ]


    def LFH_HEAP_get_LFH_SubSegment_from_SubSegmentZones(self, lfh_heap):
        """
        SubSegmentsZones and CrtZone return the same
        :param lfh_heap:
        :return:
        """
        # look at the list of LFH_BLOCK_ZONE
        for lfh_block in self.iterate_list_from_field(lfh_heap, 'SubSegmentZones'): #, ignore_head=False):
            yield lfh_block

    def LFH_HEAP_get_LFH_SubSegment_from_CrtZone(self, lfh_heap):
        """
        SubSegmentsZones and CrtZone return the same
        :param lfh_heap:
        :return:
        """
        # get the local Data
        heap_local_data = lfh_heap.LocalData[0]
        # look at the list of LFH_BLOCK_ZONE
        for lfh_block in self.iterate_list_from_pointer_field(heap_local_data, 'CrtZone'):
            yield lfh_block

    def HEAP_get_LFH_HEAP(self, record):
        addr = self._utils.get_pointee_address(record.FrontEndHeap)
        log.debug('finding frontend at @%x' % addr)
        m = self._memory_handler.get_mapping_for_address(addr)
        lfh_heap = m.read_struct(addr, self.win_heap.LFH_HEAP)
        if lfh_heap.Heap != record._orig_address_:
            log.error("heap->FrontEndHeap->Heap is not a pointer to heap")
        return lfh_heap

    def HEAP_get_LFH_chunks(self, record):
        """
        http://www.leviathansecurity.com/blog/understanding-the-windows-allocator-a-redux/
        """
        #import pdb
        #pdb.set_trace()
        from haystack.outputters import text
        out = text.RecursiveTextOutputter(self._memory_handler)
        # out = python.PythonOutputter(finder._memory_handler)
        # out.parse(ctypes_heap, depth=2)

        log.setLevel(logging.DEBUG)
        all_free = set()
        all_committed = set()
        done = set()
        lfh_heap = self.HEAP_get_LFH_HEAP(record)
        # look at the list of LFH_BLOCK_ZONE
        for lfh_block in self.LFH_HEAP_get_LFH_SubSegment_from_SubSegmentZones(lfh_heap):

            print out.parse(lfh_block, depth=1)

            # LFH_BLOCK_ZONE contains a list field to other LFH_BLOCK_ZONE, a FreePointer and a limit
            end = lfh_block._orig_address_ + self._ctypes.sizeof(lfh_block)
            fp = self._utils.get_pointee_address(lfh_block.FreePointer)
            block_length = fp - end
            subseg_size = self._ctypes.sizeof(self.win_heap.struct__HEAP_SUBSEGMENT)
            nb_subseg = block_length/subseg_size
            log.debug('LFH SUBSEGMENT: %s', hex(lfh_block._orig_address_))
            log.debug('lfh_block.FreePointer: %s', hex(fp))
            log.debug('lfh_block.Limit: %x', lfh_block.Limit)
            log.debug('block_length: %s', hex(block_length))
            log.debug('struct__HEAP_SUBSEGMENT size:%s', hex(subseg_size))
            log.debug('array of %d HEAP_SUBSEGMENT', nb_subseg)
            memory_map = self._memory_handler.get_mapping_for_address(lfh_block._orig_address_)
            segments = memory_map.read_struct(end, self.win_heap.HEAP_SUBSEGMENT*nb_subseg)
            for i, segment in enumerate(segments):
                segment_addr = end + i*subseg_size
                segment._orig_address_ = segment_addr
                log.debug('segment %d at %x', i, segment_addr)
                # struct__HEAP_SUBSEGMENT_0_0 -> BlockSize
                offset = self.win_heap.HEAP_SUBSEGMENT._3.offset
                subseg_stat = memory_map.read_struct(segment_addr+offset, self.win_heap.struct__HEAP_SUBSEGMENT_0_0)
                block_size = subseg_stat.BlockSize
                allocation_length = block_size * self._word_size_x2
                log.debug('block_size: %s', hex(block_size))
                log.debug('allocation_length: %s', hex(allocation_length))
                # struct__HEAP_SUBSEGMENT->UserBlocks
                #for block_1 in self.iterate_list_from_pointer_field(segment, 'UserBlocks'):
                #    header = self.win_heap.struct__HEAP_USERDATA_HEADER.from_buffer(block_1)
                #    print out.parse(header)
                #    print ''
                #    #if self._target.get_cpu_bits() == 32:
                #    #    struct_type = self.win_heap.struct__HEAP_ENTRY_0_0
                #    #elif self._target.get_cpu_bits() == 64:
                #    #    struct_type = self.win_heap.struct__HEAP_ENTRY_0_0_0_0
                #    #chunk_len = ctypes.sizeof(struct_type)
                #    #chunk_header_decoded = struct_type.from_buffer_copy(block_1)
                #    #print chunk_header_decoded.Size

        return all_committed, all_free

    def HEAP_get_LFH_chunks_old(self, record):
        """
        """
        import pdb
        pdb.set_trace()
        all_free = list()
        all_committed = list()
        addr = self._utils.get_pointee_address(record.FrontEndHeap)
        log.debug('finding frontend at @%x' % (addr))
        m = self._memory_handler.get_mapping_for_address(addr)
        st = m.read_struct(addr, self.win_heap.LFH_HEAP)
        # LFH is a big chunk allocated by the backend allocator, called subsegment
        # but rechopped as small chunks of a heapbin.
        # Active subsegment hold that big chunk.
        #
        #
        # load members on self.FrontEndHeap car c'est un void *
        if not self.load_members(st, 1):
            log.error('Error on loading frontend')
            raise model.NotValid('Frontend load at @%x is not valid', addr)

        # log.debug(st.LocalData[0].toString())
        #
        # 128 HEAP_LOCAL_SEGMENT_INFO
        for sinfo in st.LocalData[0].SegmentInfo:
            # TODO , what about ActiveSubsegment ?
            for items_ptr in sinfo.CachedItems:  # 16 caches items max
                items_addr = self._utils.get_pointee_address(items_ptr)
                if not bool(items_addr):
                    #log.debug('NULL pointer items')
                    continue
                m = self._memory_handler.get_mapping_for_address(items_addr)
                subsegment = m.read_struct(items_addr, self.win_heap.HEAP_SUBSEGMENT)
                # log.debug(subsegment)
                # TODO current subsegment.SFreeListEntry is on error at some depth.
                # bad pointer value on the second subsegment
                chunks = self.HEAP_SUBSEGMENT_get_userblocks(subsegment)
                free = self.HEAP_SUBSEGMENT_get_freeblocks(subsegment)
                committed = set(chunks) - set(free)
                all_free.extend(free)
                all_committed.extend(committed)
                log.debug('subseg: 0x%0.8x, commit: %d chunks free: %d chunks' % (items_addr, len(committed), len(free)))
        return all_committed, all_free

    def HEAP_get_segment_list(self, record):
        """returns a list of all segment attached to one Heap structure."""
        segments = list()
        # self heap is already one segment, but it listed in the list
        # segment = self.win_heap.HEAP_SEGMENT.from_buffer(record)
        # now the list content.
        for segment in self.iterate_list_from_field(record, 'SegmentList'):
            segment_addr = segment._orig_address_
            first_addr = self._utils.get_pointee_address(segment.FirstEntry)
            last_addr = self._utils.get_pointee_address(segment.LastValidEntry)
            log.debug(
                'Heap.Segment: 0x%0.8x FirstEntry: 0x%0.8x LastValidEntry: 0x%0.8x' %
                (segment_addr, first_addr, last_addr))
            segments.append(segment)
        segments.sort(key=lambda s:self._utils.get_pointee_address(s.FirstEntry))
        return segments

    def print_heap_analysis_details(self, heap):
        # size & space calculated from heap info
        ucrs = self.HEAP_get_UCRanges_list(heap)
        ucr_list = winheap.UCR_List(ucrs)
        # heap.Counters.TotalMemoryReserved.value == heap.LastValidEntry.value - heap.BaseAddress.value
        nb_ucr = heap.Counters.TotalUCRs
        print '\tUCRList: %d/%d' % (len(ucrs), nb_ucr)
        print ucr_list.to_string('\t\t')
        # Virtual Allocations
        vallocs = self.HEAP_get_virtual_allocated_blocks_list(heap)
        print '\tVAllocations: %d' % len(vallocs)
        for addr, c_size, r_size in vallocs:
            diff = '' if c_size == r_size else '!!'
            # print "vallocBlock: @0x%0.8x commit: 0x%x reserved: 0x%x" % (
            print "\t\t%svalloc: 0x%0.8x-0x%0.8x size:0x%x requested:0x%x " % (diff, addr, addr+c_size, c_size, r_size)
        return ucrs

    def print_frontend_analysis_details(self, heap):
        # Frontend Type == LFH
        if heap.FrontEndHeapType == 2:
            lfh_heap = self.HEAP_get_LFH_HEAP(heap)
            blocks_1 = sorted([hex(b._orig_address_) for b in self.LFH_HEAP_get_LFH_SubSegment_from_SubSegmentZones(lfh_heap)])
            print '\t\tBlocks from lfh_heap->SubSegmentZones: %d\n\t\t\t\t%s' % (len(blocks_1), blocks_1)
            blocks_2 = sorted([hex(b._orig_address_) for b in self.LFH_HEAP_get_LFH_SubSegment_from_CrtZone(lfh_heap)])
            print '\t\tBlocks from lfh_heap->LocaData[0].CrtZone: %d\n\t\t\t\t%s' % (len(blocks_2), blocks_2)
        return

    def print_segments_analysis(self, heap, walker, ucrs):
        # heap is a segment
        segments = self.HEAP_get_segment_list(heap)
        nb_segments = heap.Counters.TotalSegments
        ucr_list = winheap.UCR_List(ucrs)

        overhead_size = self._memory_handler.get_target_platform().get_target_ctypes().sizeof(self.win_heap.struct__HEAP_ENTRY)
        # get allocated/free stats by segment
        occupied_res2 = self.count_by_segment(segments, walker.get_user_allocations(), overhead_size)
        free_res2 = self.count_by_segment(segments, walker.get_free_chunks(), overhead_size)

        print "\tSegmentList: %d/%d" % (len(segments), nb_segments)
        # print ".SegmentList.Flink", hex(heap.SegmentList.Flink.value)
        # print ".SegmentList.Blink", hex(heap.SegmentList.Blink.value)
        # print ".SegmentListEntry.Flink", hex(heap.SegmentListEntry.Flink.value)
        # print ".SegmentListEntry.Blink", hex(heap.SegmentListEntry.Blink.value)
        for segment in segments:
            p_segment = winheap.Segment(self._memory_handler, segment)
            p_segment.set_ucr(ucr_list)
            p_segment.set_ressource_usage(occupied_res2, free_res2)
            print p_segment.to_string('\t\t')
            # if UCR, then
            ucrsegments = self.get_UCR_segment_list(heap)
            #print "\t\t\tUCRSegmentList: %d {%s}" % (len(ucrsegments), ','.join(sorted([hex(s._orig_address_) for s in ucrsegments])))
            print "\t\t\tUCRSegmentList: %d " % len(ucrsegments)
            for ucr in ucrsegments:
                _addr = self._utils.get_pointee_address(ucr.Address)
                end = _addr + ucr.Size
                print "\t\t\t\tUCRSegment 0x%0.8x-0x%0.8x size:0x%x" % (_addr, end, ucr.Size)
            # print ".UCRSegmentList.Blink", hex(heap.UCRSegmentList.Blink.value)