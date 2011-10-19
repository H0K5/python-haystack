#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2011 Loic Jaquemet loic.jaquemet+python@gmail.com
#

import logging
import numpy

log = logging.getLogger('utils')



def closestFloorValueNumpy(val, lst):
  ''' return the closest previous value to where val should be in lst (or val)
   please use numpy.array for lst
  ''' 
  indicetab = numpy.searchsorted(lst, [val])
  ind = indicetab[0]
  i = max(0,ind-1)
  return lst[i], i

def closestFloorValueOld(val, lst):
  ''' return the closest previous value to val in lst '''
  if val in lst:
    return val, lst.index(val)
  prev = lst[0]
  for i in xrange(1, len(lst)-1):
    if lst[i] > val:
      return prev, i-1
    prev = lst[i]
  return lst[-1], len(lst)-1

closestFloorValue = closestFloorValueNumpy
  

def dequeue(addrs, start, end):
  ''' 
  dequeue address and return vaddr in interval ( Config.WORDSIZE ) from a list of vaddr
  dequeue addrs from 0 to start.
    dequeue all value between start and end in retval2
  return remaining after end, retval2
  '''
  ret = []
  while len(addrs)> 0  and addrs[0] < start:
    addrs.pop(0)
  while len(addrs)> 0  and addrs[0] >= start and addrs[0] <= end - Config.WORDSIZE:
    ret.append(addrs.pop(0))
  return addrs, ret


