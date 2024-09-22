echo processsend收到审核指令:$1
object=$(echo $1 | awk '{print $1}')
command=$(echo $1 | awk '{print $2}')
flag=$(echo $1 | awk '{print $3}')

