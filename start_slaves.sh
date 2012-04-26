#!/bin/bash

CNT=$1
PORT_BASE=6700
JOBSERVER=http://localhost:6697

for i in $(seq ${CNT})
do
    PORT=$(($PORT_BASE+$i))
    SPATH="s${i}"
    echo "Slave $i running in $SPATH listening to $PORT"
    mkdir -p ${SPATH}
    python slave.py --path ${SPATH} --port ${PORT} ${JOBSERVER} &
done

echo "Slaves started. Waiting for them to complete"
wait
killall python
