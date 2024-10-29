#!/usr/bin/env python

import io
import logging

from pymp4.parser import Box

log = logging.getLogger(__name__)

# convert fMP4 to MP4 without rewriting the entire file
mangle_existing_boxes = True

def find_box(parent, name):
    res = None

    for box in parent.data.children:
        if box.type == name:
            res = box
            break

        if hasattr(box.data, 'children'):
            res = find_box(box, name)
            if res:
                break

    return res


moofs = []
moov = None

with open('hzd_frag_default.mp4', 'rb') as fd:
    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)

    with open('out_modified.mp4', 'wb') as fo:
        while fd.tell() < eof:
            box = Box.parse_stream(fd)

            # nullify existing moof, moov, and mfra boxes
            if box.type in {'moov', 'moof', 'mfra'}:
                if box.type == 'moof':
                    moofs.append(box)
                elif box.type == 'moov':
                    moov = box

                tmp = Box.build(box)
                if mangle_existing_boxes:
                    fo.write(tmp[:4])
                    # felt cute, this way the file is technically restorable to fMP4
                    if box.type == 'moov':
                        fo.write(b'obsm')
                    elif box.type == 'moof':
                        fo.write(b'obsf')
                    elif box.type == 'mfra':
                        fo.write(b'obsa')
                    else:
                        fo.write(b'skip')
                    fo.write(tmp[8:])
                else:
                    fo.write(tmp)

            elif box.type == 'ftyp':
                # might as well
                box.data.compatible_brands = [brand for brand in box.data.compatible_brands if brand != 'iso6']
                box.data.compatible_brands.insert(2, 'obs1')
                print(box)
                fo.write(Box.build(box))
            else:
                fo.write(Box.build(box))

        # create new MOOV box based on the data we got
        hdlr = find_box(moov, 'hdlr')
        hdlr.data.name = 'OBS Studio Muxer'

        # get sample information from moof shit
        samples = 0
        sample_dur = 0
        sync_points = []
        sample_offsets = []
        sample_counts = []
        sample_sizes = []

        first_chunks = []
        chunks_samples = []
        chunk_offsets = []

        for idx, moof in enumerate(moofs, start=1):
            tfhd = find_box(moof, 'tfhd')
            if tfhd.data.flags.default_sample_duration_present:
                sample_dur = tfhd.data.default_sample_duration

            trun = find_box(moof, 'trun')
            sync_points.append(samples + 1)
            frag_samples = trun.data.sample_count
            samples += frag_samples

            chunk_offsets.append(trun.data.data_offset + tfhd.data.base_data_offset)

            if not chunks_samples or chunks_samples[-1] != frag_samples:
                chunks_samples.append(frag_samples)
                first_chunks.append(idx)

            for sample_info in trun.data.sample_info:
                offset = sample_info.sample_composition_time_offsets
                sample_sizes.append(sample_info.sample_size)

                if sample_offsets and sample_offsets[-1] == offset:
                    sample_counts[-1] += 1
                else:
                    sample_offsets.append(offset)
                    sample_counts.append(1)

        stbl = find_box(moov, 'stbl')

        # fixup stts atom
        stts = find_box(moov, 'stts')
        stts.data.entries.append(dict(sample_count=samples, sample_delta=sample_dur))

        # create stss atom
        # todo figure out if there's a better way
        _stss = Box.build(dict(type='stss', data=dict(entries=[dict(sample_number=i) for i in sync_points])))
        stss = Box.parse(_stss)
        stbl.data.children.insert(2, stss)

        # ctts
        _ctts = Box.build(dict(type='ctts', data=dict(entries=[dict(sample_count=i, sample_offset=j) for i, j in zip(sample_counts, sample_offsets)])))
        ctts = Box.parse(_ctts)
        stbl.data.children.insert(3, ctts)

        # stsc
        stsc = find_box(moov, 'stsc')
        for idx, smp in zip(first_chunks, chunks_samples):
            stsc.data.entries.append(dict(first_chunk=idx, samples_per_chunk=smp, sample_description_index=1))

        # stsz
        stsz = find_box(moov, 'stsz')
        stsz.data.sample_size = 0
        stsz.data.sample_count = samples
        stsz.data.entry_sizes = sample_sizes

        # stco
        stco = find_box(moov, 'stco')
        stco.data.entries = [dict(chunk_offset=i) for i in chunk_offsets]

        # durations in mvhd, tkhd, and mdhd
        duration = sample_dur * samples  # todo samples can have varying durations

        mdhd = find_box(moov, 'mdhd')
        mdhd.data.duration = duration

        # for some reason this can have a different time scale
        mvhd = find_box(moov, 'mvhd')
        mvhd.data.duration = int(duration * mvhd.data.timescale / mdhd.data.timescale)
        tkhd = find_box(moov, 'tkhd')
        tkhd.data.duration = int(duration * mvhd.data.timescale / mdhd.data.timescale)

        # remove mvex and edit list
        trak = find_box(moov, 'trak')
        trak.data.children = [i for i in trak.data.children if i.type not in {'edts'}]
        moov.data.children = [i for i in moov.data.children if i.type not in {'mvex'}]

        # todo overwrite size of first mdat to make entire file `mdat` without having to rewrite it.

        fo.write(Box.build(moov))

