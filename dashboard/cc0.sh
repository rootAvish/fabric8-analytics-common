REPOS="f8a-server-backbone fabric8-analytics-data-model fabric8-analytics-jobs fabric8-analytics-license-analysis fabric8-analytics-server fabric8-analytics-stack-analysis fabric8-analytics-tagger fabric8-analytics-worker fabric8-gemini-server"

for repo in $REPOS
do
    echo ${repo}
    cp ${repo}.coverage.1.txt ${repo}.coverage.0.txt
    cp ${repo}.coverage.txt ${repo}.coverage.1.txt
done

