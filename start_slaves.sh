#!/bin/bash

CNT=$1
PORT_BASE=6700
JOBSERVER=http://localhost:6697
HOSTNAME=`hostname`

for i in $(seq ${CNT})
do
    PORT=$(($PORT_BASE+$i))
    SPATH="s${i}"
    echo "Slave $i running in $SPATH listening to $PORT"
    mkdir -p ${SPATH}
    NICK=${HOSTNAME}-${PORT}
    python scigent.py --path ${SPATH} --port ${PORT} --nick ${NICK} ${JOBSERVER}
done
